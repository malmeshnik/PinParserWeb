from celery import shared_task
from loguru import logger

from apps.tasks.models import TaskStatus, ParseTask
from apps.results.services.excel_writer import ExcelWriter


@shared_task(bind=True)
def export_results_to_excel(self, task_id: int):
    task = ParseTask.objects.get(id=task_id)

    if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        return 

    task.celery_task_id = self.request.id
    task.save(update_fields=["celery_task_id"])

    try:
        writer = ExcelWriter()
        path = writer.write_task_results(task)

        task.mark_success()

        logger.info(
            f"[EXCEL] Export finished for task #{task.id}: {path}"
        )
    except Exception as e:
        logger.exception(f"Export task {task_id} failed")
        task.mark_failed(str(e))
        raise
