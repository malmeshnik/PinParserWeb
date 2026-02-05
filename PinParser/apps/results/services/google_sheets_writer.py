from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from django.conf import settings
from loguru import logger

from apps.results.models import PinResult
from apps.tasks.models import ParseTask


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsWriter:
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

    def __init__(self):
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_FILE,
            scopes=SCOPES,
        )
        print(settings.GOOGLE_SERVICE_ACCOUNT_FILE)

        self.service = build("sheets", "v4", credentials=creds)

    def write_task_results(self, task: ParseTask):
        sheet_id = self._get_or_create_sheet(task)
        self._write_headers(sheet_id)
        self._write_rows(sheet_id, task)

        return sheet_id

    def _get_or_create_sheet(self, task: ParseTask) -> str:
        if task.table_name:
            return task.table_name

        spreadsheet = self.service.spreadsheets().create(
            body={
                "properties": {
                    "title": task.name or f"Task {task.id}"
                }
            }
        ).execute()

        sheet_id = spreadsheet["spreadsheetId"]

        task.table_name = sheet_id
        task.save(update_fields=["table_name"])

        logger.info(
            f"[SHEETS] Created sheet for task #{task.id}"
        )

        return sheet_id

    def _write_headers(self, sheet_id: str):
        self.service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="RAW",
            body={
                "values": [self.HEADERS]
            }
        ).execute()

    def _write_rows(self, sheet_id: str, task: ParseTask):
        batch_size = settings.GOOGLE_SHEETS_BATCH_SIZE
        rows = []

        qs = PinResult.objects.filter(task=task).order_by("id")

        for pin in qs.iterator(chunk_size=batch_size):
            rows.append([
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

            if len(rows) >= batch_size:
                self._append(sheet_id, rows)
                rows.clear()

        if rows:
            self._append(sheet_id, rows)

    def _append(self, sheet_id: str, rows: list[list]):
        self.service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="A2",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={
                "values": rows
            }
        ).execute()
