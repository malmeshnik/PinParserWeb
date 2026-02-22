from asgiref.sync import sync_to_async
import asyncio
import random
from urllib.parse import urlparse
from loguru import logger
from playwright.async_api import Error as PlaywrightError

from django.core.cache import cache

from asgiref.sync import sync_to_async
from workers.browser_factory import BrowserFactory


SCROLL_PAUSE_RANGE = (1, 3)
MAX_SCROLLS_PER_PAGE = 500
MAX_SAME_HEIGHT = 10
NETWORK_FLUSH_SIZE = 50


class PinterestWorker:
    def __init__(self, account, task, headless=True):
        self.account = account
        self.task = task
        self.headless = headless
        self.factory = BrowserFactory(account, headless=headless)
        self.playwright = None
        self.browser = None
        self.context = None

    async def start(self):
        self.playwright, self.browser, self.context = await self.factory.launch()

    async def stop(self):
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Error during worker stop: {e}")

    async def collect_urls_for_keyword(self, keyword: str) -> list[str]:
        if not self.context:
            raise Exception("Browser context not started. Call start() first.")

        seen: set[str] = set()
        collected_urls: list[str] = []

        page = await self.context.new_page()

        try:
            await self._listen_network(
                page,
                seen,
                collected_urls,
            )

            if self._should_stop():
                return []

            logger.info(f"[{keyword}] Starting search")

            response = await page.goto(
                f"https://www.pinterest.com/search/pins/?q={keyword}",
                timeout=60_000,
            )

            if response and not response.ok:
                logger.warning(f"[{keyword}] Page load failed: {response.status}")
                raise Exception(f"Pinterest error {response.status}")

            await asyncio.sleep(3)

            last_height = await self._safe_get_scroll_height(page)
            same_height_count = 0
            scrolls = 0

            while scrolls < MAX_SCROLLS_PER_PAGE:
                if self._should_stop():
                    logger.info(f"[{keyword}] Stopping by user request")
                    break

                await self._extract_pins_dom(page, collected_urls, seen)

                await page.mouse.wheel(0, random.randint(600, 1200))
                await asyncio.sleep(random.uniform(*SCROLL_PAUSE_RANGE))

                new_height = await self._safe_get_scroll_height(page)
                if new_height is None:
                    break

                if new_height == last_height:
                    same_height_count += 1
                else:
                    same_height_count = 0
                    last_height = new_height

                scrolls += 1

                if same_height_count >= MAX_SAME_HEIGHT:
                    break

            logger.info(f"[{keyword}] Done. Total URLs: {len(collected_urls)}")

        except Exception as e:
            logger.error(f"[{keyword}] Error: {e}")
            raise e
        finally:
            await page.close()

        return collected_urls



    async def _listen_network(
        self,
        page,
        seen: set[str],
        bucket: list[str],
    ):
        async def handle_response(response):
            if "BaseSearchResource/get" not in response.url:
                return

            try:
                data = await response.json()
            except Exception:
                return

            results = (
                data.get("resource_response", {})
                    .get("data", {})
                    .get("results", [])
            )

            for pin in results:
                pin_id = pin.get("id")

                if not pin_id or not pin_id.isdigit():
                    continue

                pin_url = f"https://www.pinterest.com/pin/{pin_id}/"

                if pin_url not in seen:
                    seen.add(pin_url)
                    bucket.append(pin_url)

        page.on("response", handle_response)



    async def _extract_pins_dom(self, page, bucket: list[str], seen: set[str]):
        try:
            links = await page.query_selector_all("a[href^='/pin/']")
            for link in links:
                href = await link.get_attribute("href")
                if not href:
                    continue

                normalized = self._normalize_pin_url(href)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    bucket.append(normalized)
        except PlaywrightError:
            pass

    async def _safe_get_scroll_height(self, page) -> int | None:
        try:
            return await page.evaluate("document.body.scrollHeight")
        except PlaywrightError:
            return None

    @sync_to_async
    def _log_to_db(self, message):
        from apps.logs.models import ErrorLog
        ErrorLog.objects.create(
            task=self.task,
            account=self.account,
            message=message[:5000]
        )

    @staticmethod
    def _normalize_pin_url(href: str) -> str | None:
        parsed = urlparse(href)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "pin":
            return f"https://www.pinterest.com/pin/{parts[1]}/"
        return None

    def _should_stop(self) -> bool:
        return cache.get(f"stop_task_{self.task.id}") is True
