import asyncio
import random
from urllib.parse import urlparse
from loguru import logger
from playwright.async_api import Error as PlaywrightError

from workers.browser_factory import BrowserFactory



SCROLL_PAUSE_RANGE = (0.8, 1.4)
MAX_SCROLLS_PER_PAGE = 200
SCROLLS_PER_ROUND = 2
MAX_SAME_HEIGHT = 5


class PinterestWorker:
    def __init__(self, account, headless=True):
        self.account = account
        self.factory = BrowserFactory(account, headless=headless)

        self.pin_urls_by_keyword: dict[str, set[str]] = {}

        self.global_pin_urls: set[str] = set()

        self.pages = {}

    async def collect_pin_urls(self, keywords: list[str]) -> dict:
        playwright, browser, context = await self.factory.launch()

        try:
            for keyword in keywords:
                page = await context.new_page()

                await page.goto(
                    f"https://www.pinterest.com/search/pins/?q={keyword}",
                    timeout=60_000
                )

                height = await page.evaluate("document.body.scrollHeight")

                self.pin_urls_by_keyword[keyword] = set()

                self.pages[keyword] = {
                    "page": page,
                    "scrolls": 0,
                    "pins": self.pin_urls_by_keyword[keyword],
                    "last_height": height,
                    "same_height": 0,
                    "done": False,
                }

            active = True
            while active:
                active = False

                for keyword, data in self.pages.items():
                    if data["done"]:
                        continue

                    if data["scrolls"] >= MAX_SCROLLS_PER_PAGE:
                        data["done"] = True
                        continue

                    page = data["page"]
                    await page.bring_to_front()

                    for _ in range(SCROLLS_PER_ROUND):
                        await self._extract_pins(page, data["pins"])

                        await page.evaluate(
                            "window.scrollTo(0, document.body.scrollHeight)"
                        )
                        await asyncio.sleep(random.uniform(*SCROLL_PAUSE_RANGE))

                        current_height = await self._safe_get_scroll_height(page)

                        if current_height == data["last_height"]:
                            data["same_height"] += 1
                        else:
                            data["same_height"] = 0
                            data["last_height"] = current_height

                        data["scrolls"] += 1
                        active = True

                        if data["same_height"] >= MAX_SAME_HEIGHT:
                            logger.info(
                                f"[{keyword}] No more content, stopping scroll"
                            )
                            data["done"] = True
                            break

            for keyword, urls in self.pin_urls_by_keyword.items():
                for url in urls:
                    self.global_pin_urls.add(url)

        finally:
            for data in self.pages.values():
                await data["page"].close()

            await browser.close()
            await playwright.stop()

        logger.info(
            f"Collected {len(self.global_pin_urls)} unique pin URLs "
            f"from {len(keywords)} keywords"
        )

        return {
            "by_keyword": self.pin_urls_by_keyword,
            "all": self.global_pin_urls,
        }
    
    def collect_pin_urls_with_keywords(
        self,
        keywords: list[str],
    ) -> dict[str, set[str]]:
        results = asyncio.run(self.collect_pin_urls(keywords))
        return results
    
    async def _safe_get_scroll_height(self, page) -> int | None:
        try:
            return await page.evaluate("document.body.scrollHeight")
        except PlaywrightError:
            return None

    async def _extract_pins(self, page, bucket: set[str]):
        links = await page.query_selector_all("a[href^='/pin/']")

        for link in links:
            href = await link.get_attribute("href")
            if not href:
                continue

            bucket.add(self._normalize_pin_url(href))

    @staticmethod
    def _normalize_pin_url(href: str) -> str:
        parsed = urlparse(href)
        parts = parsed.path.strip("/").split("/")

        if len(parts) < 2:
            return None

        pin_id = parts[1]
        return f"https://www.pinterest.com/pin/{pin_id}/"
