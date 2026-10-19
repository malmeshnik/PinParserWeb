"""Дані для дашборду моніторингу."""
import shutil
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncHour
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.logs.models import ErrorLog, LogSource, LogLevel
from apps.tasks.models import (
    ParseTask, TaskStatus, AutoPostConfig, AutoPostStatus, AutoPostQueue, PostQueueStatus,
)

# Воркери з docker-compose / systemd: ім'я ноди -> черга
EXPECTED_WORKERS = {
    "parser": "Парсинг",
    "ai": "Уникализация",
    "export": "Экспорт",
    "autopost": "Автопостинг",
}
QUEUES = ["parser", "ai", "export", "autopost"]

# Задачі за розкладом beat: (назва, як часто має запускатись)
BEAT_TASKS = [
    ("apps.tasks.tasks.process_autopost_queue", "Обработка очереди автопостинга", timedelta(minutes=3)),
    ("apps.logs.tasks.cleanup_old_logs", "Очистка старых логов", timedelta(days=1)),
]

ACTIVE_TASK_STATUSES = (TaskStatus.RUNNING, TaskStatus.WAITING_UNIQUENESS, TaskStatus.UNIQUENESS)
TASK_TIME_LIMIT = timedelta(seconds=10800)


def _timed(func):
    start = time.monotonic()
    try:
        func()
        return True, round((time.monotonic() - start) * 1000), None
    except Exception as e:
        return False, None, str(e)


def check_services():
    db_ok, db_ms, db_err = _timed(lambda: connection.cursor().execute("SELECT 1"))

    def _cache_roundtrip():
        cache.set("monitor:ping", 1, 10)
        if cache.get("monitor:ping") != 1:
            raise RuntimeError("cache read mismatch")
    redis_ok, redis_ms, redis_err = _timed(_cache_roundtrip)

    disk = None
    try:
        usage = shutil.disk_usage(settings.MEDIA_ROOT)
        disk = {
            "total_gb": round(usage.total / 1024 ** 3, 1),
            "free_gb": round(usage.free / 1024 ** 3, 1),
            "used_percent": round(usage.used / usage.total * 100),
        }
    except Exception:
        pass

    return {
        "db": {"ok": db_ok, "ms": db_ms, "error": db_err},
        "redis": {"ok": redis_ok, "ms": redis_ms, "error": redis_err},
        "disk": disk,
    }


def _queue_lengths(app):
    lengths = {}
    try:
        with app.connection_for_read() as conn:
            client = conn.default_channel.client
            for name in QUEUES:
                # kombu (redis) зберігає пріоритети в окремих ключах: name, name\x06\x163, ...
                keys = [name] + [f"{name}\x06\x16{p}" for p in (3, 6, 9)]
                lengths[name] = sum(client.llen(k) for k in keys)
    except Exception as e:
        return None, str(e)
    return lengths, None


def check_workers():
    """Стан Celery-воркерів. Кешується на 15 секунд — опитування воркерів займає ~1-2 с."""
    cached = cache.get("monitor:workers")
    if cached:
        return cached

    from config.celery import app

    result = {"workers": [], "queues": {}, "error": None}

    def _inspect(method):
        # limit — повертаємось, щойно відповіли всі очікувані воркери, а не чекаємо весь timeout
        inspect = app.control.inspect(timeout=1.5, limit=len(EXPECTED_WORKERS))
        return getattr(inspect, method)() or {}

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            stats, active, active_queues = pool.map(_inspect, ["stats", "active", "active_queues"])
    except Exception as e:
        stats, active, active_queues = {}, {}, {}
        result["error"] = str(e)

    seen_prefixes = set()
    for node, info in sorted(stats.items()):
        prefix = node.split("@")[0]
        seen_prefixes.add(prefix)
        pool = info.get("pool", {}) or {}
        result["workers"].append({
            "node": node,
            "title": EXPECTED_WORKERS.get(prefix, prefix),
            "online": True,
            "queues": [q.get("name") for q in active_queues.get(node, [])],
            "concurrency": pool.get("max-concurrency"),
            "active": [
                {"name": t.get("name", "").rsplit(".", 1)[-1], "args": t.get("args"),
                 "started": t.get("time_start")}
                for t in active.get(node, [])
            ],
            "processed": sum((info.get("total") or {}).values()),
            "uptime_h": round((info.get("uptime") or 0) / 3600, 1),
        })

    for prefix, title in EXPECTED_WORKERS.items():
        if prefix not in seen_prefixes:
            result["workers"].append({"node": f"{prefix}@…", "title": title, "online": False})

    lengths, queue_error = _queue_lengths(app)
    result["queues"] = lengths or {}
    result["queue_error"] = queue_error

    cache.set("monitor:workers", result, 15)
    return result


def check_beat():
    now = timezone.now()
    items = []
    for name, title, interval in BEAT_TASKS:
        last = cache.get(f"monitor:task_last:{name}")
        last_at = parse_datetime(last["at"]) if last else None
        # Запас: 2 інтервали + 2 хвилини
        ok = bool(last_at and now - last_at <= interval * 2 + timedelta(minutes=2))
        items.append({
            "title": title, "last_at": last_at, "state": last.get("state") if last else None,
            "ok": ok, "interval": interval,
        })
    return items


def task_stats():
    now = timezone.now()
    by_status = dict(ParseTask.objects.values_list("status").annotate(c=Count("id")))
    statuses = [
        {"value": value, "label": label, "count": by_status.get(value, 0)}
        for value, label in TaskStatus.choices
    ]

    active = list(
        ParseTask.objects.filter(status__in=ACTIVE_TASK_STATUSES + (TaskStatus.PENDING,))
        .select_related("owner").order_by("-started_at")[:20]
    )
    for task in active:
        task.is_stuck = bool(
            task.status in ACTIVE_TASK_STATUSES and task.started_at and now - task.started_at > TASK_TIME_LIMIT
        )
        task.progress = round(task.processed_urls / task.total_urls * 100) if task.total_urls else 0

    failed = list(
        ParseTask.objects.filter(status=TaskStatus.ERROR, finished_at__gte=now - timedelta(days=7))
        .order_by("-finished_at")[:10]
    )
    finished_24h = ParseTask.objects.filter(finished_at__gte=now - timedelta(hours=24))

    return {
        "statuses": statuses,
        "active": active,
        "failed": failed,
        "done_24h": finished_24h.filter(status=TaskStatus.DONE).count(),
        "error_24h": finished_24h.filter(status=TaskStatus.ERROR).count(),
    }


def autopost_stats():
    now = timezone.now()
    day = now - timedelta(hours=24)
    by_status = dict(AutoPostConfig.objects.values_list("status").annotate(c=Count("id")))

    running = list(
        AutoPostConfig.objects.filter(status=AutoPostStatus.RUNNING)
        .select_related("task", "uniqueness_config")
        .order_by("task__name")
    )
    for config in running:
        next_item = (
            config.queue_items.filter(status=PostQueueStatus.PENDING).order_by("scheduled_at").first()
        )
        config.next_at = next_item.scheduled_at if next_item else None
        config.overdue = bool(config.next_at and now - config.next_at > timedelta(minutes=10))

    return {
        "statuses": [
            {"value": value, "label": label, "count": by_status.get(value, 0)}
            for value, label in AutoPostStatus.choices
        ],
        "running": running,
        "errors": list(AutoPostConfig.objects.filter(status=AutoPostStatus.ERROR).select_related("task")[:10]),
        "posted_24h": AutoPostQueue.objects.filter(status=PostQueueStatus.POSTED, posted_at__gte=day).count(),
        "failed_24h": AutoPostQueue.objects.filter(status=PostQueueStatus.FAILED, created_at__gte=day).count(),
        "pending": AutoPostQueue.objects.filter(
            status=PostQueueStatus.PENDING, config__status=AutoPostStatus.RUNNING
        ).count(),
    }


def error_stats():
    now = timezone.now()
    hour, day, week = now - timedelta(hours=1), now - timedelta(hours=24), now - timedelta(days=7)
    errors = ErrorLog.objects.all()
    real_errors = errors.exclude(level=LogLevel.WARNING)

    totals = {
        "hour": real_errors.filter(created_at__gte=hour).count(),
        "day": real_errors.filter(created_at__gte=day).count(),
        "week": real_errors.filter(created_at__gte=week).count(),
        "warnings_day": errors.filter(level=LogLevel.WARNING, created_at__gte=day).count(),
        "unresolved": real_errors.filter(is_resolved=False).count(),
    }

    # По джерелах за 24 год
    source_rows = {
        row["source"]: row
        for row in errors.filter(created_at__gte=day).values("source").annotate(
            errors=Count("id", filter=~Q(level=LogLevel.WARNING)),
            warnings=Count("id", filter=Q(level=LogLevel.WARNING)),
            last=Max("created_at"),
        )
    }
    by_source = [
        {
            "value": value, "label": label,
            "errors": source_rows.get(value, {}).get("errors", 0),
            "warnings": source_rows.get(value, {}).get("warnings", 0),
            "last": source_rows.get(value, {}).get("last"),
        }
        for value, label in LogSource.choices
    ]

    # Погодинний графік за 24 год
    per_hour = dict(
        real_errors.filter(created_at__gte=day)
        .annotate(h=TruncHour("created_at")).values_list("h").annotate(c=Count("id"))
    )
    start = timezone.localtime(now).replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    hours = []
    for i in range(24):
        h = start + timedelta(hours=i)
        count = next((c for k, c in per_hour.items() if k and timezone.localtime(k) == h), 0)
        hours.append({"hour": h, "count": count})
    max_count = max((h["count"] for h in hours), default=0) or 1
    for h in hours:
        h["height"] = round(h["count"] / max_count * 100)

    # Найчастіші помилки за 7 днів
    top = list(
        errors.filter(created_at__gte=week).exclude(fingerprint="")
        .values("fingerprint", "source", "level")
        .annotate(count=Count("id"), last=Max("created_at"), last_id=Max("id"))
        .order_by("-count")[:10]
    )
    messages = dict(ErrorLog.objects.filter(id__in=[t["last_id"] for t in top]).values_list("id", "message"))
    source_labels = dict(LogSource.choices)
    for item in top:
        item["message"] = (messages.get(item["last_id"]) or "").splitlines()[0][:200] if messages.get(item["last_id"]) else ""
        item["source_label"] = source_labels.get(item["source"], item["source"])

    recent = list(errors.select_related("task").order_by("-created_at")[:25])

    return {"totals": totals, "by_source": by_source, "hours": hours, "top": top, "recent": recent}


def collect():
    return {
        "services": check_services(),
        "celery": check_workers(),
        "beat": check_beat(),
        "tasks": task_stats(),
        "autopost": autopost_stats(),
        "errors": error_stats(),
        "generated_at": timezone.now(),
    }
