from celery import shared_task
from loguru import logger
from django.core.cache import cache

from apps.tasks.models import ParseTask, TaskStatus
from apps.parser.services.pipeline import PinterestParsePipeline
from apps.results.tasks import export_results_to_excel
from apps.uniqueness.tasks import run_uniqueness, generate_slugs


@shared_task(bind=True, time_limit=10800)
def run_parse_task(self, task_id: int):

    lock_key = f"parse_task_lock_{task_id}"

    lock_acquired = cache.add(lock_key, self.request.id, timeout=10800)

    if not lock_acquired:
        logger.warning(f"Task {task_id} already running. Skipping duplicate.")
        return {"skipped": True}

    task = ParseTask.objects.get(id=task_id)

    try:
        task.mark_running(self.request.id)

        pipeline = PinterestParsePipeline(
            task=task,
            headless=True,
        )

        parsed_count = pipeline.run()

        task.refresh_from_db()

        if task.status == TaskStatus.STOPPED:
            return {"parsed": parsed_count}

        if task.use_uniqueness:
            task.mark_wait_uniqueness()
            (
                run_uniqueness.s(task.id)
                | generate_slugs.si(task.id)
                | export_results_to_excel.si(task.id)
            ).apply_async()
        else:
            export_results_to_excel.delay(task.id)

        if task.status != TaskStatus.ERROR:
            task.mark_success()

        return {"parsed": parsed_count}

    except Exception as e:
        logger.exception(f"Parse task {task_id} failed")
        task.mark_failed(str(e))
        raise

    finally:
        current_lock = cache.get(lock_key)

        if current_lock == self.request.id:
            cache.delete(lock_key)

        task.refresh_from_db()
        task.celery_task_id = None
        task.save(update_fields=["celery_task_id"])