from celery import shared_task
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.uniqueness.services.ai_uniqueness_service import AIUniquenessService
from apps.uniqueness.services.slug_service import SlugService
from apps.results.models import PinResult
from apps.tasks.models import TaskStatus, ParseTask
from apps.tasks.services.task_control import clear_stop_flag


def _start_step(task: ParseTask, celery_task_id: str, chained: bool) -> bool:
    """
    Переводить задачу в статус уникалізації.
    chained=True — крок ланцюжка після парсингу: пропускаємо, якщо задачу зупинено або вона впала.
    chained=False — ручний запуск з адмінки.
    """
    if chained and task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        return False

    if not chained:
        clear_stop_flag(task.id)

    task.status = TaskStatus.UNIQUENESS
    task.celery_task_id = celery_task_id
    task.save(update_fields=["status", "celery_task_id"])
    return True


def _finish_step(task: ParseTask, chained: bool):
    task.refresh_from_db(fields=["status"])
    if not chained and task.status != TaskStatus.STOPPED:
        task.mark_success()


@shared_task(bind=True, time_limit=10800)
def run_uniqueness(self, task_id: int, chained: bool = False):
    task = ParseTask.objects.get(id=task_id)

    if not _start_step(task, self.request.id, chained):
        return

    try:
        config = task.uniqueness_config or UniquenessConfig.objects.filter(is_active=True).first()
        if not config:
            raise RuntimeError("Не знайдено активного конфігу уникалізації")

        qs = PinResult.objects.filter(task_id=task_id, utitle__isnull=True)
        result = AIUniquenessService(task, config).process_queryset(qs)

        if result.stopped:
            return

        if result.fatal_error:
            raise RuntimeError(f"Помилка API уникалізації: {result.fatal_error}")

        if result.failed and not result.succeeded:
            raise RuntimeError(
                f"Не вдалося уникалізувати жодного піна ({result.failed} шт.). "
                f"Остання помилка: {result.last_error}"
            )

        if result.failed:
            task.add_note(
                f"Не уникалізовано {result.failed} з {result.failed + result.succeeded} пінів. "
                f"Остання помилка: {result.last_error}"
            )

        _finish_step(task, chained)
    except Exception as e:
        logger.exception(f"Uniqueness task {task_id} failed")
        task.mark_failed(str(e))
        raise


@shared_task(bind=True)
def generate_slugs(self, task_id: int, chained: bool = False):
    task = ParseTask.objects.get(id=task_id)

    if not _start_step(task, self.request.id, chained):
        return

    qs = PinResult.objects.filter(
        task_id=task_id,
        slug_url__isnull=True,
        utitle__isnull=False,
    )

    try:
        for pin in qs.iterator(chunk_size=200):
            pin.slug_url = SlugService.build_slug_url(
                pin_id=None,
                utitle=pin.utitle,
                base_url="xxx"
            )
            pin.save(update_fields=["slug_url"])

        _finish_step(task, chained)
    except Exception as e:
        logger.exception(f"Generate slugs task {task_id} failed")
        task.mark_failed(str(e))
        raise
