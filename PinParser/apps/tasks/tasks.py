from celery import shared_task
from django.utils import timezone
from loguru import logger

from apps.tasks.models import ParseTask, TaskStatus
from apps.accounts.models import PinterestAccount
from apps.parser.services.pipeline import PinterestParsePipeline
from apps.results.tasks import export_results_to_excel
from apps.uniqueness.tasks import run_uniqueness, generate_slugs


@shared_task(bind=True)
def run_parse_task(self, task_id: int):
    task = ParseTask.objects.get(id=task_id)

    try:
        task.mark_running(self.request.id)

        pipeline = PinterestParsePipeline(
            task=task,
            headless=True,
        )

        parsed_count = pipeline.run()
        task.mark_success(parsed_count)

        # Post-processing chain
        if task.use_uniqueness:
            # We chain uniqueness -> slug generation -> sheets export
            (run_uniqueness.s(task.id) | generate_slugs.si(task.id) | export_results_to_excel.si(task.id)).apply_async()
        else:
            export_results_to_excel.delay(task.id)

        return {"parsed": parsed_count}

    except Exception as e:
        logger.exception(f"Parse task {task_id} failed")
        task.mark_failed(str(e))
        raise
