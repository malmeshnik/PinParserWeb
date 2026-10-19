from celery import shared_task
from loguru import logger

from apps.tasks.models import TaskStatus, ParseTask
from apps.results.services.excel_writer import ExcelWriter


@shared_task(bind=True)
def export_results_to_excel(self, task_id: int, chained: bool = False):
    """
    chained=True — фінальний крок після парсингу/уникалізації, виставляє статус задачі.
    chained=False — ручний експорт з адмінки, статус задачі не змінює.
    """
    task = ParseTask.objects.get(id=task_id)

    if chained:
        if task.status in (TaskStatus.ERROR, TaskStatus.STOPPED):
            return

        task.celery_task_id = self.request.id
        task.save(update_fields=["celery_task_id"])

    try:
        path = ExcelWriter().write_task_results(task)

        if chained:
            task.refresh_from_db(fields=["status"])
            if task.status != TaskStatus.STOPPED:
                task.mark_success()

        logger.info(
            f"[EXCEL] Export finished for task #{task.id}: {path}"
        )
    except Exception as e:
        logger.exception(f"Export task {task_id} failed")
        if chained:
            task.mark_failed(str(e))
        raise
