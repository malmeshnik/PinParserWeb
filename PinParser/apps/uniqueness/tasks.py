from celery import shared_task
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.uniqueness.services.ai_uniqueness_service import AIUniquenessService
from apps.uniqueness.services.slug_service import SlugService
from apps.results.models import PinResult
from apps.tasks.models import TaskStatus, ParseTask

@shared_task(bind=True, time_limit=10800)
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
            return

        service = AIUniquenessService(task, config)

        service.process_queryset(qs)

        if mark_done:
            task.mark_success()
    except Exception as e:
        logger.exception(f"Uniqueness task {task_id} failed")
        task.mark_failed(str(e))
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
                pin_id=None,
                utitle=pin.utitle,
                base_url="xxx"
            )
            pin.save(update_fields=["slug_url"])

        if mark_done:
            task.mark_success()
    except Exception as e:
        logger.exception(f"Generate slugs task {task_id} failed")
        task.mark_failed(str(e))
        raise