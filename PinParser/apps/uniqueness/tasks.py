from celery import shared_task
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.uniqueness.services.ai_uniqueness_service import AIUniquenessService
from apps.uniqueness.services.slug_service import SlugService
from apps.results.models import PinResult
from apps.tasks.models import TaskStatus, ParseTask


@shared_task(bind=True)
def run_uniqueness(self, task_id: int, mark_done: bool = True):
    qs = PinResult.objects.filter(
        task_id=task_id,
        utitle__isnull=True,
    )

    task = ParseTask.objects.get(id=task_id)

    if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        return

    task.status = TaskStatus.UNIQUENESS
    task.celery_task_id = self.request.id
    task.save(update_fields=["status", "celery_task_id"])

    try:
        if task.uniqueness_config:
            config = task.uniqueness_config
        else:
            config = UniquenessConfig.objects.filter(is_active=True).first()

        if not config:
            logger.error(f"[UNIQUENESS] No active config found for task {task_id}")
            return

        service = AIUniquenessService(task, config)

        service.process_queryset(qs)

        # Check if there are failed pins and schedule retry
        if service.failed_pin_ids:
            failed_count = len(service.failed_pin_ids)
            logger.info(f"[UNIQUENESS] Scheduling retry for {failed_count} failed pins")

            # Schedule retry after 2 minutes to avoid immediate rate limit
            retry_uniqueness.apply_async(
                args=[task_id, service.failed_pin_ids],
                countdown=120
            )

        if mark_done:
            task.mark_success()
    except Exception as e:
        logger.exception(f"Uniqueness task {task_id} failed")
        task.mark_failed(str(e))
        raise


@shared_task(bind=True, max_retries=0)
def retry_uniqueness(self, task_id: int, pin_ids: list[int]):
    """Retry failed pins with a longer delay between requests."""
    logger.info(f"[UNIQUENESS] Retrying {len(pin_ids)} failed pins for task {task_id}")

    qs = PinResult.objects.filter(
        task_id=task_id,
        id__in=pin_ids,
        utitle__isnull=True,
    )

    actual_count = qs.count()
    if actual_count == 0:
        logger.info(f"[UNIQUENESS] No pins to retry - all already processed")
        return

    task = ParseTask.objects.get(id=task_id)

    if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        logger.info(f"[UNIQUENESS] Task {task_id} is stopped or in error state, skipping retry")
        return

    try:
        if task.uniqueness_config:
            config = task.uniqueness_config
        else:
            config = UniquenessConfig.objects.filter(is_active=True).first()

        if not config:
            logger.error(f"[UNIQUENESS] No active config found for retry task {task_id}")
            return

        service = AIUniquenessService(task, config)
        service.process_queryset(qs)

        # Final check - if still have failures, log them
        if service.failed_pin_ids:
            logger.error(
                f"[UNIQUENESS] {len(service.failed_pin_ids)} pins still failed after retry. "
                f"Manual intervention may be needed. IDs: {service.failed_pin_ids}"
            )

    except Exception:
        logger.exception(f"Retry uniqueness task {task_id} failed")
        raise


@shared_task(bind=True)
def generate_slugs(self, task_id: int, mark_done: bool = True):
    qs = PinResult.objects.filter(
        task_id=task_id,
        slug_url__isnull=True,
        utitle__isnull=False,
    )
    task = ParseTask.objects.get(id=task_id)

    if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        return

    task.status = TaskStatus.UNIQUENESS
    task.celery_task_id = self.request.id
    task.save(update_fields=["status", "celery_task_id"])

    try:
        for pin in qs.iterator(chunk_size=200):
            pin.slug_url = SlugService.build_slug_url(
                pin_id=None, utitle=pin.utitle, base_url="xxx"
            )
            pin.save(update_fields=["slug_url"])

        if mark_done:
            task.mark_success()
    except Exception as e:
        logger.exception(f"Generate slugs task {task_id} failed")
        task.mark_failed(str(e))
        raise
