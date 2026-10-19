"""
Збір помилок у таблицю ErrorLog з усіх процесів (web, Celery-воркери, beat).

Джерела:
  * loguru — всі logger.error / logger.exception / logger.critical;
    logger.warning лише з logger.bind(db=True).warning(...);
  * стандартний logging (Django, Celery) — рівень ERROR і вище;
  * Celery-сигнали — падіння задач, включно з time limit і втраченим воркером.

Запис у БД іде через фоновий потік: логування не блокує роботу, працює з async-коду
(Playwright) і не зациклюється, якщо сама БД недоступна.

Контекст (яка задача парсингу, яка Celery-задача, воркер) береться з поточної Celery-задачі —
у prefork-воркері процес виконує одну задачу за раз, тому вистачає змінної на процес,
і її бачать також потоки ThreadPoolExecutor всередині задачі.
"""
import hashlib
import logging
import os
import queue
import re
import sys
import threading
import traceback as tb_module

from loguru import logger

MAX_MESSAGE = 5000
MAX_TRACEBACK = 20000

# Celery-задачі, у яких перший аргумент — ID ParseTask
PARSE_TASK_ARG_TASKS = {
    "apps.tasks.tasks.run_parse_task",
    "apps.uniqueness.tasks.run_uniqueness",
    "apps.uniqueness.tasks.generate_slugs",
    "apps.results.tasks.export_results_to_excel",
}

# Логери стандартного logging, які дублюють те, що ми вже записали іншим шляхом
SKIP_STD_LOGGERS = ("celery.app.trace",)

_current = {}          # контекст поточної Celery-задачі в цьому процесі
_installed = False
_queue = None
_writer_pid = None
_writer_lock = threading.Lock()


# ---------- визначення джерела ----------

def _source_from_celery_task(name: str) -> str | None:
    if not name:
        return None
    if "autopost" in name:
        return "autopost"
    if name.startswith("apps.tasks.tasks.run_parse_task"):
        return "parser"
    if name.startswith("apps.uniqueness."):
        return "uniqueness"
    if name.startswith("apps.results."):
        return "export"
    return "celery"


def _source_from_module(name: str) -> str | None:
    if not name:
        return None
    if name.startswith("apps.tasks.services.autopost"):
        return "autopost"
    if name.startswith(("workers.", "apps.parser.", "apps.proxies.", "apps.accounts.")):
        return "parser"
    if name.startswith("apps.uniqueness."):
        return "uniqueness"
    if name.startswith("apps.results."):
        return "export"
    if name.startswith(("django.request", "django.server", "gunicorn", "apps.core.")):
        return "web"
    if name.startswith(("celery", "kombu")):
        return "celery"
    return None


def _detect_source(explicit, module_name):
    if explicit:
        return explicit
    # Модулі автопостингу визначаємо до контексту задачі: тест автопостингу запускається з вебу
    module_source = _source_from_module(module_name)
    if module_source == "autopost":
        return module_source
    return _source_from_celery_task(_current.get("celery_task_name")) or module_source or "system"


# ---------- відпечаток для групування ----------

_NORMALIZE_RE = [
    (re.compile(r"https?://\S+"), "<url>"),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<uuid>"),
    (re.compile(r"\d+(\.\d+)?"), "N"),
]


def make_fingerprint(source: str, message: str) -> str:
    text = (message or "").strip().splitlines()[0] if message else ""
    for pattern, repl in _NORMALIZE_RE:
        text = pattern.sub(repl, text)
    return hashlib.sha1(f"{source}|{text[:300]}".encode("utf-8", "ignore")).hexdigest()


# ---------- запис у БД фоновим потоком ----------

def _ensure_writer():
    global _queue, _writer_pid
    pid = os.getpid()
    if _writer_pid == pid:
        return
    with _writer_lock:
        if _writer_pid == pid:
            return
        # Після fork (prefork-воркер Celery) потік батьківського процесу не існує — створюємо свій
        _queue = queue.Queue(maxsize=10000)
        threading.Thread(target=_writer_loop, args=(_queue,), name="errorlog-writer", daemon=True).start()
        _writer_pid = pid


def _writer_loop(q):
    from django.db import close_old_connections

    while True:
        item = q.get()
        try:
            close_old_connections()
            _save(item)
        except Exception as e:  # БД недоступна тощо — не логуємо через loguru, щоб не зациклитись
            print(f"[ErrorLog] failed to save log entry: {e!r} | {item.get('message', '')[:200]}", file=sys.stderr)
        finally:
            q.task_done()


def _save(item):
    from apps.logs.models import ErrorLog
    from apps.tasks.models import ParseTask
    from apps.accounts.models import PinterestAccount

    task_id = item.pop("task_id", None)
    account_id = item.pop("account_id", None)
    if task_id and not ParseTask.objects.filter(id=task_id).exists():
        task_id = None
    if account_id and not PinterestAccount.objects.filter(id=account_id).exists():
        account_id = None

    ErrorLog.objects.create(task_id=task_id, account_id=account_id, **item)


def _to_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def record_error(
    message: str,
    *,
    level: str = "ERROR",
    source: str | None = None,
    traceback: str = "",
    logger_name: str = "",
    module_name: str = "",
    task_id=None,
    account_id=None,
    context: dict | None = None,
):
    """Поставити запис у чергу на збереження. Ніколи не кидає виключень."""
    try:
        _ensure_writer()
        source = _detect_source(source, module_name or logger_name)

        ctx = {k: v for k, v in _current.items() if k != "task_id"}
        ctx.update(context or {})

        message = (message or "").strip() or "(порожнє повідомлення)"
        item = {
            "message": message[:MAX_MESSAGE],
            "level": level if level in ("WARNING", "ERROR", "CRITICAL") else "ERROR",
            "source": source,
            "traceback": (traceback or "")[-MAX_TRACEBACK:],
            "logger_name": (logger_name or "")[:255],
            "context": _json_safe(ctx),
            "fingerprint": make_fingerprint(source, message),
            "task_id": _to_int(task_id) or _current.get("task_id"),
            "account_id": _to_int(account_id),
        }
        _queue.put_nowait(item)
    except Exception as e:
        print(f"[ErrorLog] failed to queue log entry: {e!r}", file=sys.stderr)


def flush(timeout: float = 5.0):
    """Дочекатися запису всіх помилок з черги (для тестів і завершення процесу)."""
    if _queue is None or _writer_pid != os.getpid():
        return
    done = threading.Event()

    def _wait():
        _queue.join()
        done.set()

    threading.Thread(target=_wait, daemon=True).start()
    done.wait(timeout)


def _format_exception(exc_type, exc_value, exc_tb) -> str:
    return "".join(tb_module.format_exception(exc_type, exc_value, exc_tb))


def _mark_logged(exc):
    try:
        exc._errorlog_recorded = True
    except Exception:
        pass


# ---------- loguru ----------

EXTRA_CONTEXT_KEYS = ("pin_id", "autopost_config_id", "keyword", "url")


def _loguru_sink(message):
    record = message.record
    extra = record["extra"]

    if extra.get("skip_db"):
        return
    if record["level"].no < 40 and not extra.get("db"):  # WARNING — тільки явно позначені
        return

    traceback = ""
    exc = record["exception"]
    if exc and exc.type:
        traceback = _format_exception(exc.type, exc.value, exc.traceback)
        _mark_logged(exc.value)

    record_error(
        record["message"],
        level=record["level"].name if record["level"].name in ("WARNING", "ERROR", "CRITICAL") else "ERROR",
        source=extra.get("source"),
        traceback=traceback,
        logger_name=f"{record['name']}:{record['function']}:{record['line']}",
        module_name=record["name"] or "",
        task_id=extra.get("task_id"),
        account_id=extra.get("account_id"),
        context={k: extra[k] for k in EXTRA_CONTEXT_KEYS if k in extra},
    )


# ---------- стандартний logging ----------

class DatabaseLogHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record):
        if record.name.startswith(SKIP_STD_LOGGERS):
            return
        try:
            traceback = ""
            if record.exc_info and record.exc_info[0]:
                traceback = _format_exception(*record.exc_info)
                _mark_logged(record.exc_info[1])

            context = {}
            request = getattr(record, "request", None)
            if request is not None:
                user = getattr(request, "user", None)
                context = {
                    "method": getattr(request, "method", ""),
                    "path": getattr(request, "get_full_path", lambda: "")(),
                    "user": getattr(user, "username", None) if user and user.is_authenticated else None,
                }
            status_code = getattr(record, "status_code", None)
            if status_code:
                context["status_code"] = status_code

            record_error(
                record.getMessage(),
                level=record.levelname,
                traceback=traceback,
                logger_name=f"{record.name}:{record.funcName}:{record.lineno}",
                module_name=record.name,
                context=context,
            )
        except Exception:
            pass


def _attach_std_handler(target_logger: logging.Logger):
    if not any(isinstance(h, DatabaseLogHandler) for h in target_logger.handlers):
        target_logger.addHandler(DatabaseLogHandler())


# ---------- Celery ----------

def _parse_task_id_from_args(task_name, args, kwargs):
    if task_name in PARSE_TASK_ARG_TASKS:
        value = (kwargs or {}).get("task_id") or (args[0] if args else None)
        return _to_int(value)
    return None


def _on_task_prerun(sender=None, task_id=None, task=None, args=None, kwargs=None, **_):
    name = getattr(task, "name", "") or ""
    _current.clear()
    _current.update({
        "celery_task_name": name,
        "celery_task_id": task_id,
        "worker": getattr(getattr(task, "request", None), "hostname", None),
    })
    parse_task_id = _parse_task_id_from_args(name, args, kwargs)
    if parse_task_id:
        _current["task_id"] = parse_task_id
    if name.endswith("initialize_autopost_queue") and args:
        _current["autopost_config_id"] = args[0]


def _on_task_postrun(sender=None, task_id=None, task=None, state=None, retval=None, **_):
    from django.core.cache import cache
    from django.utils import timezone

    name = getattr(task, "name", "") or ""
    try:
        # Для дашборду: коли і з яким результатом задача виконувалась востаннє
        cache.set(f"monitor:task_last:{name}", {"at": timezone.now().isoformat(), "state": state}, timeout=7 * 24 * 3600)
    except Exception:
        pass
    _current.clear()


def _on_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, einfo=None, **_):
    name = getattr(sender, "name", "") or ""

    _mark_parse_task_failed(name, exception, args, kwargs)

    if getattr(exception, "_errorlog_recorded", False):
        return  # вже записано з logger.exception всередині задачі

    traceback = str(einfo) if einfo else ""
    record_error(
        f"Celery-задача {name} впала: {type(exception).__name__}: {exception}",
        level="ERROR",
        source=_source_from_celery_task(name),
        traceback=traceback,
        logger_name=name,
        task_id=_parse_task_id_from_args(name, args, kwargs),
        context={"celery_task_name": name, "celery_task_id": task_id, "args": args, "kwargs": kwargs},
    )


def _mark_parse_task_failed(task_name, exception, args, kwargs):
    """
    Якщо задачу вбито (time limit, втрачений воркер), її код не встигає поставити статус
    і завдання вічно висить «В процесі». Ставимо помилку тут.
    """
    from celery.exceptions import TimeLimitExceeded, WorkerLostError

    if not isinstance(exception, (TimeLimitExceeded, WorkerLostError)):
        return
    parse_task_id = _parse_task_id_from_args(task_name, args, kwargs)
    if not parse_task_id:
        return
    try:
        from apps.tasks.models import ParseTask, TaskStatus

        task = ParseTask.objects.filter(id=parse_task_id).first()
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING,
                                    TaskStatus.WAITING_UNIQUENESS, TaskStatus.UNIQUENESS):
            reason = "перевищено ліміт часу" if isinstance(exception, TimeLimitExceeded) else "процес воркера аварійно завершився"
            task.mark_failed(f"Задачу примусово завершено: {reason} ({type(exception).__name__}: {exception})")
    except Exception as e:
        print(f"[ErrorLog] failed to mark task {parse_task_id} as failed: {e!r}", file=sys.stderr)


def _on_setup_logger(logger=None, **_):
    if logger is not None:
        _attach_std_handler(logger)


# ---------- встановлення ----------

def install():
    global _installed
    if _installed:
        return
    _installed = True

    logger.add(_loguru_sink, level="WARNING", format="{message}", catch=True)
    _attach_std_handler(logging.getLogger())

    from celery import signals
    signals.task_prerun.connect(_on_task_prerun, weak=False)
    signals.task_postrun.connect(_on_task_postrun, weak=False)
    signals.task_failure.connect(_on_task_failure, weak=False)
    # Celery-воркер перевизначає root-логер при старті — підключаємо обробник знову
    signals.after_setup_logger.connect(_on_setup_logger, weak=False)
    signals.after_setup_task_logger.connect(_on_setup_logger, weak=False)
