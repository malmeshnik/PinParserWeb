from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from loguru import logger

from apps.tasks.models import ParseTask, TaskStatus
from workers.pinterest_worker import PinterestWorker
from workers.pin_fetcher import PinFetcher
from .pin_parser import PinParser
from apps.proxies.models import Proxy
from apps.tasks.models import ParseTask
from apps.accounts.models import PinterestAccount
from apps.results.models import PinResult

class PinterestParsePipeline:
    def __init__(
        self,
        task: ParseTask,
        account: PinterestAccount,
        proxy: Proxy | None = None,
        headless: bool = True,
        max_pins: int | None = None,
    ):
        self.task = task
        self.proxy = proxy
        self.account = account
        self.headless = headless
        self.max_pins = max_pins

        self.worker = PinterestWorker(account=account, headless=headless)
        self.fetcher = PinFetcher(proxy=proxy)
        self.parser = PinParser()

        self.urls_by_keyword: dict[str, set[str]] = defaultdict(set)

    def run(self) -> list[dict]:
        logger.info(f"[PIPELINE] Start task #{self.task.id}")

        self._collect_urls()
        self._fetch_and_parse_threaded()

        logger.info(
            f"[PIPELINE] Finished | "
        )
        return self.task.processed_urls
    
    def _collect_urls(self):
        urls_map = self.worker.collect_pin_urls_with_keywords(
            self.task.keywords
        )

        total = 0

        for keyword, urls in urls_map.items():
            self.urls_by_keyword[keyword].update(urls)
            total += len(urls)

        self.task.total_urls = total
        self.task.processed_urls = 0
        self.task.save(update_fields=["total_urls", "processed_urls"])

        logger.info(
            f"[PIPELINE] Collected {total} URLs for task #{self.task.id}"
        )

    def _fetch_and_parse_threaded(self):
        max_workers = max(1, self.task.threads)
        logger.info(
            f"[PIPELINE] Fetch+parse with {max_workers} threads"
        )

        processed = 0
        batch_update_every = 5

        def worker_job(keyword: str, pin_url: str):
            if self.task.status == TaskStatus.STOPPED:
                return None

            html = self.fetcher.fetch(pin_url)
            if not html:
                return None

            return self.parser.parse(
                html=html,
                pin_url=pin_url,
                keyword=keyword,
            )

        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for keyword, urls in self.urls_by_keyword.items():
                for pin_url in urls:
                    futures.append(
                        executor.submit(worker_job, keyword, pin_url)
                    )

            for future in as_completed(futures):
                if self.task.status == TaskStatus.STOPPED:
                    logger.warning(
                        f"[PIPELINE] Task #{self.task.id} stopped"
                    )
                    break

                data = future.result()
                processed += 1

                if data:
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
                # тут пізніше: save result / sheets / uniqueness
                self._update_progress(processed, batch_update_every)

    def _update_progress(self, processed: int, batch: int):
        if processed % batch != 0:
            return

        ParseTask.objects.filter(id=self.task.id).update(
            processed_urls=processed
        )


    def stats(self) -> dict:
        return {
            "keywords": len(self.keywords),
            "pins": len(self.task.processed_urls),
        }