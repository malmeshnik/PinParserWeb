import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

from loguru import logger
from django.utils import timezone
from django.db.models import F
from django.core.cache import cache
from asgiref.sync import sync_to_async

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
            if self._should_stop():
                logger.info(f"Task {self.task.name} Stopping by user request")
                msg = "Зупинено адміном"
                break

            account.last_used_at = timezone.now()
            account.save(update_fields=["last_used_at"])

            success = self._run_with_account(account)
            
            logger.info(f"[PIPELINE] Trying account ID={account.id}")

            if success:
                self._fetch_and_parse_pins(account)
                return self.task.processed_urls

            self._handle_account_failure(account)

        msg = "Не вдалося зібрати піни жодним з доступних аккаунтів"
        self._fail_task(msg)
        return 0

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
            if account.status == AccountStatus.ERROR:
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

        max_threads = min(3, self.task.threads)
        semaphore = asyncio.Semaphore(max_threads)

        logger.info(
            f"[PIPELINE] Collecting URLs for {len(keywords)} keywords "
            f"using account ID={account.id} (async, max_threads={max_threads})"
        )

        worker = PinterestWorker(
            account=account,
            task=self.task,
            headless=self.headless,
        )

        total = 0
        errors = 0

        await worker.start()
        try:
            async def semaphore_wrapper(kw):
                nonlocal total, errors
                if errors >= 3:
                    return

                async with semaphore:
                    if errors >= 3:
                        return

                    try:
                        urls = await worker.collect_urls_for_keyword(kw)

                        new_count = len(urls)

                        if new_count > 0:
                            self.urls_by_keyword[kw].update(urls)
                            total += new_count
                            await self._increment_total_urls(new_count)
                        logger.info(
                            f"[PIPELINE] Keyword '{kw}' collected {len(urls)} pins"
                        )
                    except Exception as e:
                        errors += 1
                        # Increment account failure count for each error
                        await sync_to_async(account.register_fail)()
                        logger.error(f"[PIPELINE] Error for keyword {kw}: {e}")
                        # We don't call self._log_error here because worker.collect_urls_for_keyword already logs to DB

            await asyncio.gather(*(semaphore_wrapper(kw) for kw in keywords))
        finally:
            await worker.stop()

        self.task.total_urls = total
        await sync_to_async(self.task.save)(update_fields=["total_urls"])

        if errors >= 3:
            raise Exception(f"Account encountered {errors} errors, stopping collection.")

        if keywords and errors == len(keywords) and total == 0:
            raise Exception("Всі запити завершилися з помилкою")

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
                if self._should_stop():
                    logger.info(f"Stopping by user request")
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

    def _should_stop(self) -> bool:
        return cache.get(f"stop_task_{self.task.id}") is True
    
    @sync_to_async
    def _increment_total_urls(self, amount: int):
        ParseTask.objects.filter(id=self.task.id).update(
            total_urls=F("total_urls") + amount
        )

    def _should_stop(self) -> bool:
        return cache.get(f"stop_task_{self.task.id}") is True
