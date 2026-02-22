from celery import shared_task
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.uniqueness.services.ai_uniqueness_service import AIUniquenessService
from apps.uniqueness.services.slug_service import SlugService
from apps.results.models import PinResult
from apps.tasks.models import TaskStatus, ParseTask

@shared_task
def run_uniqueness(task_id: int, time_limit=10800):
    qs = PinResult.objects.filter(
        task_id=task_id,
        utitle__isnull=True,
    )

    task = ParseTask.objects.get(id=task_id)
    
    logger.info(f"Task Status: {task.status}")
    if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        return 
    
    task.status = TaskStatus.UNIQUENESS
    task.save(update_fields=["status"])

    if task.uniqueness_config:
        config = task.uniqueness_config
    else:
        config = UniquenessConfig.objects.filter(is_active=True).first()

    if not config:
        return

    service = AIUniquenessService(config)

    service.process_queryset(qs)
    task.mark_success()

@shared_task
def generate_slugs(task_id: int):
    qs = PinResult.objects.filter(
        task_id=task_id,
        slug_url__isnull=True,
        utitle__isnull=False,
    )
    task = ParseTask.objects.get(id=task_id)

    logger.info(f"Task Status: {task.status}")
    if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        return 
    
    task.status = TaskStatus.UNIQUENESS
    task.save(update_fields=["status"])

    for pin in qs.iterator(chunk_size=200):
        pin.slug_url = SlugService.build_slug_url(
            pin_id=None,
            utitle=pin.utitle,
            base_url="xxx"
        )
        pin.save(update_fields=["slug_url"])

    task.mark_success()