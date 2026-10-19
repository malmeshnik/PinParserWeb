from django.core.cache import cache
from django.utils import timezone

from apps.tasks.models import ParseTask, TaskStatus
from config.celery import app

ACTIVE_STATUSES = (
    TaskStatus.RUNNING,
    TaskStatus.WAITING_UNIQUENESS,
    TaskStatus.UNIQUENESS,
)


def stop_flag_key(task_id: int) -> str:
    return f"stop_task_{task_id}"


def parse_lock_key(task_id: int) -> str:
    return f"parse_task_lock_{task_id}"


def is_stop_requested(task_id: int) -> bool:
    return cache.get(stop_flag_key(task_id)) is True


def clear_stop_flag(task_id: int):
    cache.delete(stop_flag_key(task_id))


def start_parse_task(task: ParseTask) -> bool:
    """Ставить задачу парсингу в чергу. Повертає False, якщо вона вже виконується."""
    from apps.tasks.tasks import run_parse_task

    if task.status in ACTIVE_STATUSES:
        return False

    clear_stop_flag(task.id)

    # Статус виставляємо ДО відправки в чергу, інакше воркер може встигнути
    # поставити RUNNING, а ми перезапишемо його на PENDING
    task.status = TaskStatus.PENDING
    task.save(update_fields=["status"])

    result = run_parse_task.delay(task.id)
    ParseTask.objects.filter(id=task.id).update(celery_task_id=result.id)
    return True


def stop_parse_task(task: ParseTask) -> bool:
    """Зупиняє задачу на будь-якому етапі. Повертає False, якщо зупиняти нічого."""
    if task.status not in (TaskStatus.PENDING, *ACTIVE_STATUSES):
        return False

    cache.set(stop_flag_key(task.id), True, timeout=3600)

    if task.celery_task_id:
        app.control.revoke(task.celery_task_id, terminate=True, signal="SIGTERM")

    # Після terminate блок finally в run_parse_task не виконується,
    # тому лок знімаємо тут — інакше перезапуск буде пропущено як дубль
    cache.delete(parse_lock_key(task.id))

    task.status = TaskStatus.STOPPED
    task.celery_task_id = None
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "celery_task_id", "finished_at"])
    return True
