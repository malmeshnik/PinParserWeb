import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

from loguru import logger
from django.utils import timezone
from django.db.models import F
from asgiref.sync import sync_to_async

from apps.tasks.models import ParseTask
from apps.tasks.services.task_control import is_stop_requested
from apps.accounts.models import PinterestAccount, AccountStatus
from apps.results.models import PinResult
from apps.results.services.image_download_service import ImageDownloadService
from workers.pinterest_worker import PinterestWorker
from workers.pin_fetcher import PinFetcher
from .pin_parser import PinParser


class PipelineError(Exception):
    pass


class PinterestParsePipeline:
    def __init__(self, task: ParseTask, headless: bool = True):
        self.task = task
        self.headless = headless
        self.parser = PinParser()
        self.image_downloader = ImageDownloadService()
        self.urls_by_keyword = defaultdict(set)
        self.max_threads = max(1, min(3, self.task.threads))
        self.annotation_filter_words = [
            word.strip().lower()
            for word in (self.task.annotation_filter_words or "").split(",")
            if word.strip()
        ]

    def run(self) -> int:
        """Повертає кількість збережених пінів. При критичній помилці кидає PipelineError."""
        accounts = self._get_accounts()

        if not accounts:
            raise PipelineError("Немає доступних активних аккаунтів Pinterest")

        for account in accounts:
            if self._should_stop():
                logger.info(f"Task {self.task.name} Stopping by user request")
                return 0

            logger.info(f"[PIPELINE] Trying account ID={account.id}")

            account.last_used_at = timezone.now()
            account.save(update_fields=["last_used_at"])

            if self._run_with_account(account):
                return self._fetch_and_parse_pins(account)

            if self._should_stop():
                return 0

            self._handle_account_failure(account)

        raise PipelineError("Не вдалося зібрати піни жодним з доступних аккаунтів")

    def _get_accounts(self):
        return list(
            PinterestAccount.objects.select_related("proxy").filter(
                is_active=True,
                status=AccountStatus.ACTIVE
            ).order_by(
                F("last_used_at").asc(nulls_first=True)
            )
        )

    def _run_with_account(self, account: PinterestAccount) -> bool:
        for attempt in range(1, 3):
            if account.status == AccountStatus.ERROR or self._should_stop():
                break

            logger.info(
                f"[PIPELINE] Task #{self.task.id}, "
                f"Account ID={account.id}, Attempt {attempt}"
            )

            try:
                total = asyncio.run(self._collect_all_urls_async(account))
                if total > 0:
                    return True

                self._log_error(
                    f"0 pins collected for account {account.id}, attempt {attempt}",
                    account,
                )

            except Exception as e:
                self._log_error(
                    f"Error for account {account.id}, attempt {attempt}: {e}",
                    account,
                )

        return False

    def _handle_account_failure(self, account: PinterestAccount):
        logger.warning(f"[PIPELINE] Account {account.id} failed, rotating")
        account.register_fail()

    async def _collect_all_urls_async(self, account: PinterestAccount) -> int:
        keywords = self.task.keywords
        if isinstance(keywords, str):
            keywords = [keywords]

        semaphore = asyncio.Semaphore(self.max_threads)

        logger.info(
            f"[PIPELINE] Collecting URLs for {len(keywords)} keywords "
            f"using account ID={account.id} (async, max_threads={self.max_threads})"
        )

        worker = PinterestWorker(
            account=account,
            task=self.task,
            headless=self.headless,
        )

        errors = 0

        try:
            await worker.start()

            async def semaphore_wrapper(kw):
                nonlocal errors
                if errors >= 3:
                    return

                async with semaphore:
                    if errors >= 3:
                        return

                    try:
                        urls = await worker.collect_urls_for_keyword(kw)
                        self.urls_by_keyword[kw].update(urls)
                        logger.info(
                            f"[PIPELINE] Keyword '{kw}' collected {len(urls)} pins"
                        )
                    except Exception as e:
                        errors += 1
                        await sync_to_async(account.register_fail)()
                        logger.bind(task_id=self.task.id, account_id=account.id, keyword=kw).error(
                            f"[PIPELINE] Error for keyword {kw}: {e}"
                        )

            await asyncio.gather(*(semaphore_wrapper(kw) for kw in keywords))
        finally:
            await worker.stop()

        # Воркер оновлює total_urls під час скролу; тут фіксуємо точне значення
        # без дублікатів між ключовими словами і попередніми спробами
        total = len(self._unique_urls())
        await ParseTask.objects.filter(id=self.task.id).aupdate(total_urls=total)

        if errors >= 3:
            raise Exception(f"Account encountered {errors} errors, stopping collection.")

        if keywords and errors == len(keywords) and total == 0:
            raise Exception("Всі запити завершилися з помилкою")

        return total

    def _unique_urls(self) -> list[tuple[str, str]]:
        """Пари (keyword, url) без повторів url — один пін може знайтись за кількома словами."""
        seen = set()
        result = []
        for kw, urls in self.urls_by_keyword.items():
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    result.append((kw, url))
        return result

    def _fetch_and_parse_pins(self, account: PinterestAccount) -> int:
        fetcher = PinFetcher(account=account, task=self.task)
        all_urls = self._unique_urls()

        def process(kw, url):
            if self._should_stop():
                return None

            html = fetcher.fetch(url)
            if not html:
                return None

            return self.parser.parse(html, url, kw)

        saved = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = [
                executor.submit(process, kw, url)
                for kw, url in all_urls
            ]

            for future in as_completed(futures):
                if self._should_stop():
                    executor.shutdown(wait=False, cancel_futures=True)
                    logger.info("Stopping by user request")
                    return saved

                try:
                    data = future.result()
                except Exception as e:
                    logger.warning(f"[PIPELINE] Pin processing failed | {e}")
                    data = None

                if not data:
                    failed += 1
                    continue

                if self._save_result(data):
                    saved += 1

        if all_urls and failed == len(all_urls):
            raise PipelineError(
                f"Не вдалося завантажити жодного піна з {len(all_urls)} знайдених"
            )

        if failed:
            self.task.add_note(
                f"Не вдалося завантажити {failed} з {len(all_urls)} пінів, деталі в логах помилок"
            )

        return saved

    def _save_result(self, data: dict) -> bool:
        annotation = (data.get("annotation") or "").lower()

        if self.annotation_filter_words and not any(word in annotation for word in self.annotation_filter_words):
            logger.info(f"[PIPELINE] Pin {data.get('pin_id')} skipped due to annotation filter")
            return False

        image_url = data.get("image_url")
        pin_id = data.get("pin_id")

        pin_result, created = PinResult.objects.get_or_create(
            task=self.task,
            pin_url=data["pin_url"],
            defaults=data,
        )

        if not created:
            return False

        ParseTask.objects.filter(id=self.task.id).update(
            processed_urls=F("processed_urls") + 1
        )

        if image_url and pin_id:
            try:
                image_file = self.image_downloader.download_image(image_url, pin_id)
                if image_file:
                    pin_result.local_image.save(image_file.name, image_file, save=True)
                    logger.success(f"[PIPELINE] Saved local image for pin {pin_id}")
            except Exception as e:
                logger.warning(f"[PIPELINE] Failed to download image for pin {pin_id}: {e}")

        return True

    def _log_error(self, message: str, account: PinterestAccount):
        logger.bind(task_id=self.task.id, account_id=account.id).error(f"[PIPELINE] {message}")

    def _should_stop(self) -> bool:
        return is_stop_requested(self.task.id)
