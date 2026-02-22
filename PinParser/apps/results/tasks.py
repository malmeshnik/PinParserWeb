from celery import shared_task
from loguru import logger

from apps.tasks.models import TaskStatus, ParseTask
from apps.results.services.excel_writer import ExcelWriter


@shared_task
def export_results_to_excel(task_id: int):
    task = ParseTask.objects.get(id=task_id)

    if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
        return 

    writer = ExcelWriter()
    path = writer.write_task_results(task)

    logger.info(
        f"[EXCEL] Export finished for task #{task.id}: {path}"
    )
