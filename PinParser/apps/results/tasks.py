from celery import shared_task
from loguru import logger

from apps.results.services.google_sheets_writer import GoogleSheetsWriter
from apps.tasks.models import ParseTask


@shared_task
def export_results_to_sheets(task_id: int):
    task = ParseTask.objects.get(id=task_id)

    writer = GoogleSheetsWriter()
    sheet_id = writer.write_task_results(task)

    logger.info(
        f"[SHEETS] Exported task #{task.id} → {sheet_id}"
    )
