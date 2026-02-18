# apps/results/services/excel_writer.py

from openpyxl import Workbook
from django.conf import settings
from loguru import logger
from pathlib import Path

from apps.results.models import PinResult
from apps.tasks.models import ParseTask


class ExcelWriter:
    HEADERS = [
        "keyword",
        "pin_url",
        "title",
        "description",
        "utitle",
        "udescription",
        "slug_url",
        "image_url",
        "domain",
        "alt_text",
        "annotation",
        "saves",
        "pinner_username",
        "creation_date",
    ]

    def write_task_results(self, task: ParseTask) -> str:
        wb = Workbook()
        ws = wb.active
        ws.title = "Results"

        ws.append(self.HEADERS)

        qs = PinResult.objects.filter(task=task).order_by("id")

        for pin in qs.iterator(chunk_size=500):
            ws.append([
                pin.keyword,
                pin.pin_url,
                pin.title,
                pin.description,
                pin.utitle,
                pin.udescription,
                pin.slug_url,
                pin.image_url,
                pin.domain,
                pin.alt_text,
                pin.annotation,
                pin.saves,
                pin.pinner_username,
                pin.creation_date,
            ])

        export_dir = Path(settings.MEDIA_ROOT) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{task.name}.xlsx"
        filepath = export_dir / filename

        wb.save(filepath)

        task.export_file.name = f"exports/{filename}"
        task.save(update_fields=["export_file"])

        logger.info(
            f"[EXCEL] Exported task #{task.id} → {filepath}"
        )

        return str(filepath)
