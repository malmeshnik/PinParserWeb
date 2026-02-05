from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from django.conf import settings
from loguru import logger

from apps.results.models import PinResult
from apps.tasks.models import ParseTask

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


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

        self.service = build("sheets", "v4", credentials=creds)
        self.drive_service = build("drive", "v3", credentials=creds)

    def write_task_results(self, task: ParseTask):
        sheet_id = self._get_or_create_sheet(task)
        self._write_headers(sheet_id)
        self._write_rows(sheet_id, task)

        return sheet_id

    def _get_or_create_sheet(self, task: ParseTask) -> str:
        # If task already has a table_name (spreadsheetId), use it
        if task.table_name and len(task.table_name) > 20: # simple check if it looks like an ID
             return task.table_name

        title = task.name
        if task.auto_sheet_name:
            title = f"Pinterest Results - {task.name} - {task.created_at.strftime('%Y-%m-%d %H:%M')}"

        spreadsheet = self._execute_with_retry(
            self.service.spreadsheets().create(
                body={
                    "properties": {
                        "title": title
                    }
                }
            )
        )

        sheet_id = spreadsheet["spreadsheetId"]

        self._execute_with_retry(
            self.drive_service.permissions().create(
                fileId=sheet_id,
                body={
                    "type": "user",
                    "role": "writer",
                    "emailAddress": "you@gmail.com"
                }
            )
        )

        task.table_name = sheet_id
        task.save(update_fields=["table_name"])

        logger.info(
            f"[SHEETS] Created sheet '{title}' (ID: {sheet_id}) for task #{task.id}"
        )

        return sheet_id

    def _execute_with_retry(self, request, max_retries=3):
        import time
        import random
        from googleapiclient.errors import HttpError

        for i in range(max_retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status in [429, 500, 503]:
                    wait = (2 ** i) + random.random()
                    logger.warning(f"[SHEETS] Quota or server error, retrying in {wait:.2f}s...")
                    time.sleep(wait)
                else:
                    raise
        return request.execute()

    def _write_headers(self, sheet_id: str):
        self._execute_with_retry(
            self.service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range="A1",
                valueInputOption="RAW",
                body={
                    "values": [self.HEADERS]
                }
            )
        )

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
                pin.creation_date.strftime("%Y-%m-%d %H:%M:%S"),
            ])

            if len(rows) >= batch_size:
                self._append(sheet_id, rows)
                rows.clear()

        if rows:
            self._append(sheet_id, rows)

    def _append(self, sheet_id: str, rows: list[list]):
        self._execute_with_retry(
            self.service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range="A2",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={
                    "values": rows
                }
            )
        )
