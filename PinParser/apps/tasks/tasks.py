from celery import shared_task
from django.utils import timezone
from loguru import logger

from apps.tasks.models import ParseTask, TaskStatus
from apps.accounts.models import PinterestAccount
from apps.parser.services.pipeline import PinterestParsePipeline
from apps.results.tasks import export_results_to_sheets
from apps.uniqueness.tasks import run_uniqueness, generate_slugs


@shared_task(bind=True)
def run_parse_task(self, task_id: int):
    task = ParseTask.objects.get(id=task_id)

    try:
        task.status = TaskStatus.RUNNING
        task.started_at = timezone.now()
        task.celery_task_id = self.request.id
        task.save(update_fields=[
            "status", "started_at", "celery_task_id"
        ])
        account = PinterestAccount.objects.first()

        pipeline = PinterestParsePipeline(
            task=task,
            account=account,
            max_pins=None,
        )

        parsed_count = pipeline.run()

        task.status = TaskStatus.DONE
        task.finished_at = timezone.now()
        task.processed_urls = parsed_count
        task.save(update_fields=[
            "status", "finished_at", "processed_urls"
        ])

        if task.use_uniqueness:
            run_uniqueness.delay(task.id)
            generate_slugs.delay(task.id)

        export_results_to_sheets.delay(task.id)

        return {"parsed": parsed_count}

    except Exception as e:
        logger.exception("Parse task failed")

        task.status = TaskStatus.ERROR
        task.error_message = str(e)[:5000]
        task.finished_at = timezone.now()
        task.save(update_fields=[
            "status", "error_message", "finished_at"
        ])

        raise
