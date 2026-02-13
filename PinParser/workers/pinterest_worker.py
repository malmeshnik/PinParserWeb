# workers/pinterest_worker.py

import asyncio
import random
from urllib.parse import urlparse
from loguru import logger
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from asgiref.sync import sync_to_async
from workers.browser_factory import BrowserFactory
from apps.results.models import PinResult
from apps.proxies.nine_proxy import NineProxyService


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
        dom_urls: list[str] = []

        network_buffer: list[dict] = []

        page = await self.context.new_page()
        try:
            await self._listen_network(
                page,
                keyword,
                seen,
                network_buffer,
            )

            logger.info(f"[{keyword}] Starting search")

            response = await page.goto(
                f"https://www.pinterest.com/search/pins/?q={keyword}",
                timeout=60_000,
            )

            if response and not response.ok:
                logger.warning(f"[{keyword}] Page load failed: {response.status}")
                if response.status == 429:
                    raise Exception("Rate limited (429)")
                if response.status >= 500:
                    raise Exception(f"Pinterest server error ({response.status})")

            await asyncio.sleep(3)

            last_height = await self._safe_get_scroll_height(page)
            same_height_count = 0
            scrolls = 0

            while scrolls < MAX_SCROLLS_PER_PAGE:
                await self._extract_pins_dom(page, dom_urls, seen)

                if len(network_buffer) >= NETWORK_FLUSH_SIZE:
                    await self._flush_network_buffer(keyword, network_buffer)

                await page.mouse.wheel(0, random.randint(600, 1200))
                await asyncio.sleep(random.uniform(*SCROLL_PAUSE_RANGE))

                if random.random() < 0.2:
                    await page.mouse.move(
                        random.randint(100, 900),
                        random.randint(100, 700)
                    )

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

            if network_buffer:
                await self._flush_network_buffer(keyword, network_buffer)

            logger.info(
                f"[{keyword}] Done. DOM fallback URLs: {len(dom_urls)}"
            )

        except (PlaywrightTimeout, PlaywrightError) as e:
            error_msg = f"[{keyword}] Connection/Proxy error: {e}"
            logger.warning(error_msg)
            await self._log_to_db(error_msg)
            if self.account and self.account.proxy:
                # Trigger health check on failure
                logger.warning('Refreshing proxy')
                nine_proxy = NineProxyService()

                filters = {
                    "country": self.account.proxy.country,
                    "state": self.account.proxy.state,
                    "city": self.account.proxy.city,
                    "zip": self.account.proxy.zip,
                    "isp": self.account.proxy.isp,
                }
                await sync_to_async(nine_proxy._refresh_proxy)(self.account.proxy, filters)
                await sync_to_async(self.account.proxy.check_health)()
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"[{keyword}] Error: {e}"
            logger.error(error_msg)
            await self._log_to_db(error_msg)
            raise e
        finally:
            await page.close()

        return dom_urls


    async def _listen_network(
        self,
        page,
        keyword: str,
        seen: set[str],
        buffer: list[dict],
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
                if pin_url in seen:
                    continue

                seen.add(pin_url)
                buffer.append(pin)

        page.on("response", handle_response)


    async def _flush_network_buffer(self, keyword: str, buffer: list[dict]):
        objects = []

        for pin in buffer:
            pin_id = pin.get("id")

            if not pin_id or not pin_id.isdigit():
                continue

            images = pin.get("images", {})
            orig = images.get("orig", {})

            objects.append(
                PinResult(
                    task=self.task,
                    keyword=keyword,
                    pin_id=pin_id,
                    pin_url=f"https://www.pinterest.com/pin/{pin_id}/",
                    title=pin.get("title"),
                    description=pin.get("description"),
                    image_url=orig.get("url"),
                    domain=pin.get("domain"),
                    alt_text=pin.get("grid_title"),
                    annotation=pin.get("board", {}).get("name"),
                    saves=pin.get("reaction_counts", {}).get("1"),
                    pinner_username=pin.get("pinner", {}).get("username"),
                    creation_date=pin.get("created_at"),
                )
            )

        await sync_to_async(PinResult.objects.bulk_create)(
            objects,
            ignore_conflicts=True,
            batch_size=500,
        )

        buffer.clear()


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
