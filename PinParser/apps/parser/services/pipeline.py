import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

from loguru import logger
from django.utils import timezone
from django.db.models import F

from apps.tasks.models import ParseTask, TaskStatus
from apps.accounts.models import PinterestAccount, AccountStatus
from apps.results.models import PinResult
from apps.logs.models import ErrorLog
from workers.pinterest_worker import PinterestWorker
from workers.pin_fetcher import PinFetcher
from .pin_parser import PinParser


class PinterestParsePipeline:
    def __init__(self, task: ParseTask, headless: bool = True):
        self.task = task
        self.headless = headless
        self.parser = PinParser()
        self.urls_by_keyword = defaultdict(set)

    def run(self) -> int:
        accounts = self._get_accounts()

        if not accounts:
            msg = "Немає доступних активних аккаунтів Pinterest"
            self._fail_task(msg)
            return 0

        for account in accounts:
            logger.info(f"[PIPELINE] Trying account ID={account.id}")

            success = self._run_with_account(account)

            if success:
                account.last_used_at = timezone.now()
                account.save(update_fields=["last_used_at"])
                self._fetch_and_parse_pins(account)
                return self.task.processed_urls

            self._handle_account_failure(account)

        msg = "Не вдалося зібрати піни жодним з доступних аккаунтів"
        self._fail_task(msg)
        return 0

    def _get_accounts(self):
        return list(
            PinterestAccount.objects.filter(
                is_active=True,
                status=AccountStatus.ACTIVE
            ).order_by(
                F("last_used_at").asc(nulls_first=True)
            )
        )

    def _run_with_account(self, account: PinterestAccount) -> bool:
        for attempt in range(1, 3):
            logger.info(
                f"[PIPELINE] Task #{self.task.id}, "
                f"Account ID={account.id}, Attempt {attempt}"
            )

            try:
                total = self._collect_all_urls(account)
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

        account.fail_count += 1
        if account.fail_count >= 5:
            account.status = AccountStatus.ERROR

        account.save(update_fields=["fail_count", "status"])

    def _collect_all_urls(self, account: PinterestAccount) -> int:
        keywords = self.task.keywords
        if isinstance(keywords, str):
            keywords = [keywords]

        max_threads = min(3, self.task.threads)
        logger.info(
            f"[PIPELINE] Collecting URLs for {len(keywords)} keywords "
            f"using account ID={account.id}"
        )

        def job(keyword: str):
            worker = PinterestWorker(
                account=account,
                task=self.task,
                headless=self.headless,
            )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    worker.collect_urls_for_keyword(keyword)
                )
            finally:
                loop.close()

        total = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(job, kw): kw for kw in keywords}

            for future in as_completed(futures):
                kw = futures[future]
                try:
                    urls = future.result()
                    self.urls_by_keyword[kw].update(urls)
                    total += len(urls)
                    logger.info(
                        f"[PIPELINE] Keyword '{kw}' collected {len(urls)} pins"
                    )
                except Exception as e:
                    errors += 1
                    self._log_error(
                        f"Error collecting for keyword {kw}: {e}",
                        account,
                    )

        self.task.total_urls = total
        self.task.save(update_fields=["total_urls"])

        if errors == len(keywords) and total == 0:
            raise Exception("Всі потоки завершилися з помилкою")

        return total

    def _fetch_and_parse_pins(self, account: PinterestAccount):
        fetcher = PinFetcher(account=account, task=self.task)
        max_threads = min(3, self.task.threads)

        all_urls = [
            (kw, url)
            for kw, urls in self.urls_by_keyword.items()
            for url in urls
        ]

        processed = 0

        def process(kw, url):
            if self.task.status == TaskStatus.STOPPED:
                return None

            html = fetcher.fetch(url)
            if not html:
                return None

            return self.parser.parse(html, url, kw)

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = [
                executor.submit(process, kw, url)
                for kw, url in all_urls
            ]

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

    def _save_result(self, data: dict):
        PinResult.objects.get_or_create(
            task=self.task,
            pin_url=data["pin_url"],
            defaults=data,
        )

    def _fail_task(self, message: str):
        logger.error(f"[PIPELINE] {message}")
        self.task.mark_failed(message)

    def _log_error(self, message: str, account: PinterestAccount):
        logger.error(f"[PIPELINE] {message}")
        ErrorLog.objects.create(
            task=self.task,
            account=account,
            message=message[:5000],
        )
