import random
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from loguru import logger
from django.utils import timezone

from apps.tasks.models import ParseTask, TaskStatus
from apps.accounts.models import PinterestAccount, AccountStatus
from apps.results.models import PinResult
from apps.logs.models import ErrorLog
from workers.pinterest_worker import PinterestWorker
from workers.pin_fetcher import PinFetcher
from .pin_parser import PinParser

class PinterestParsePipeline:
    def __init__(
        self,
        task: ParseTask,
        account: PinterestAccount = None,
        headless: bool = True,
    ):
        self.task = task
        self.account = account or self._get_available_account()
        self.headless = headless
        self.parser = PinParser()
        self.urls_by_keyword = defaultdict(set)

        if not self.account:
            raise Exception("Немає доступних активних аккаунтів Pinterest")

    def _get_available_account(self):
        return PinterestAccount.objects.filter(
            is_active=True,
            status=AccountStatus.ACTIVE
        ).order_by('last_used_at').first()

    def run(self) -> int:
        logger.info(f"[PIPELINE] Start task #{self.task.id} with account {self.account}")

        try:
            self._collect_all_urls()

            if self.task.status == TaskStatus.STOPPED:
                return 0

            self._fetch_and_parse_pins()

            return self.task.processed_urls
        except Exception as e:
            self._log_error(str(e))
            raise e

    def _collect_all_urls(self):
        keywords = self.task.keywords
        if isinstance(keywords, str):
            keywords = [keywords]

        max_threads = min(3, self.task.threads)
        logger.info(f"[PIPELINE] Collecting URLs for {len(keywords)} keywords with {max_threads} threads")

        def collect_job(kw):
            worker = PinterestWorker(account=self.account, task=self.task, headless=self.headless)
            # We need to run the async method in a new event loop for each thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(worker.collect_urls_for_keyword(kw))
            finally:
                loop.close()

        total_collected = 0
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            future_to_kw = {executor.submit(collect_job, kw): kw for kw in keywords}
            for future in as_completed(future_to_kw):
                kw = future_to_kw[future]
                try:
                    urls = future.result()
                    self.urls_by_keyword[kw].update(urls)
                    total_collected += len(urls)
                    logger.info(f"[PIPELINE] Keyword '{kw}' collected {len(urls)} pins")
                except Exception as e:
                    self._log_error(f"Error collecting for keyword {kw}: {e}")

        self.task.total_urls = total_collected
        self.task.save(update_fields=["total_urls"])

        if total_collected == 0:
            # Maybe rotate account and retry?
            self._handle_no_results()

    def _fetch_and_parse_pins(self):
        fetcher = PinFetcher(account=self.account)
        max_threads = min(3, self.task.threads)

        all_urls = []
        for kw, urls in self.urls_by_keyword.items():
            for url in urls:
                all_urls.append((kw, url))

        processed = 0

        def process_pin(kw, url):
            if self.task.status == TaskStatus.STOPPED:
                return None

            html = fetcher.fetch(url)
            if not html:
                return None

            data = self.parser.parse(html, url, kw)
            if data:
                return data
            return None

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = [executor.submit(process_pin, kw, url) for kw, url in all_urls]
            for future in as_completed(futures):
                if self.task.status == TaskStatus.STOPPED:
                    break

                data = future.result()
                processed += 1

                if data:
                    self._save_result(data)

                if processed % 10 == 0:
                    self.task.processed_urls = processed
                    self.task.save(update_fields=["processed_urls"])

        self.task.processed_urls = processed
        self.task.save(update_fields=["processed_urls"])

    def _save_result(self, data):
        PinResult.objects.get_or_create(
            task=self.task,
            pin_url=data["pin_url"],
            defaults={
                "keyword": data["keyword"],
                "pin_id": data.get("pin_id"),
                "title": data.get("title"),
                "description": data.get("description"),
                "image_url": data.get("image_url"),
                "domain": data.get("domain"),
                "alt_text": data.get("alt_text"),
                "annotation": data.get("annotation"),
                "saves": data.get("saves"),
                "pinner_username": data.get("pinner_username"),
                "creation_date": data.get("creation_date"),
            }
        )

    def _handle_no_results(self):
        logger.warning(f"[PIPELINE] No results for task {self.task.id}. Rotating account...")
        # Mark current account as error if it consistently fails
        self.account.fail_count += 1
        if self.account.fail_count >= 5:
            self.account.status = AccountStatus.ERROR
        self.account.save()

        # In a real scenario, we might want to restart the collection with a new account here
        # But for now we just log it.

    def _log_error(self, message):
        logger.error(f"[PIPELINE] {message}")
        ErrorLog.objects.create(
            task=self.task,
            account=self.account,
            message=message[:5000]
        )
