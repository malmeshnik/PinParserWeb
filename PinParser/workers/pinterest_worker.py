import asyncio
import random
from urllib.parse import urlparse
from loguru import logger
from playwright.async_api import Error as PlaywrightError

from workers.browser_factory import BrowserFactory


SCROLL_PAUSE_RANGE = (1.0, 2.5)
MAX_SCROLLS_PER_PAGE = 100
MAX_SAME_HEIGHT = 6


class PinterestWorker:
    def __init__(self, account, headless=True):
        self.account = account
        self.headless = headless
        self.factory = BrowserFactory(account, headless=headless)

    async def collect_urls_for_keyword(self, keyword: str) -> set[str]:
        """
        Collects pin URLs for a single keyword.
        """
        playwright, browser, context = await self.factory.launch()
        pin_urls = set()

        try:
            page = await context.new_page()

            # User-Agent rotation is already in BrowserFactory

            logger.info(f"[{keyword}] Starting search")
            await page.goto(
                f"https://www.pinterest.com/search/pins/?q={keyword}",
                timeout=60_000,
                wait_until="networkidle"
            )

            last_height = await page.evaluate("document.body.scrollHeight")
            same_height_count = 0
            scrolls = 0

            while scrolls < MAX_SCROLLS_PER_PAGE:
                await self._extract_pins(page, pin_urls)

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
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
                    logger.info(f"[{keyword}] Reached end of page after {scrolls} scrolls")
                    break

            if not pin_urls:
                logger.warning(f"[{keyword}] No pins collected. Possible block or empty search.")

        except Exception as e:
            logger.error(f"[{keyword}] Error during collection: {e}")
        finally:
            await browser.close()
            await playwright.stop()

        return pin_urls

    async def _safe_get_scroll_height(self, page) -> int | None:
        try:
            return await page.evaluate("document.body.scrollHeight")
        except PlaywrightError:
            return None

    async def _extract_pins(self, page, bucket: set[str]):
        try:
            links = await page.query_selector_all("a[href^='/pin/']")
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    normalized = self._normalize_pin_url(href)
                    if normalized:
                        bucket.add(normalized)
        except PlaywrightError:
            pass

    @staticmethod
    def _normalize_pin_url(href: str) -> str | None:
        parsed = urlparse(href)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == 'pin':
            pin_id = parts[1]
            return f"https://www.pinterest.com/pin/{pin_id}/"
        return None
