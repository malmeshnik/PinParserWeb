import asyncio
import random
from urllib.parse import urlparse
from loguru import logger
from playwright.async_api import Error as PlaywrightError
from django.core.cache import cache

from workers.browser_factory import BrowserFactory


SCROLL_PAUSE_RANGE = (1.2, 2.5)
MAX_SCROLLS_PER_PAGE = 500
MAX_SAME_HEIGHT = 20


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

        # 🔥 ПРОВЕРКА ПРОКСИ
        try:
            page = await self.context.new_page()

            resp = await page.goto("https://ipinfo.io/json", timeout=15000)
            data = await resp.json()

            logger.info(f"""
[PROXY CHECK]
IP: {data.get('ip')}
Country: {data.get('country')}
City: {data.get('city')}
Org: {data.get('org')}
""")

            await page.close()

        except Exception as e:
            logger.error(f"[PROXY ERROR] Proxy not working: {e}")
            raise Exception("Proxy failed, stopping worker")

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
            raise Exception("Browser context not started")

        page = await self.context.new_page()

        seen: set[str] = set()
        collected_urls: list[str] = []

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

                if not pin_id or not str(pin_id).isdigit():
                    continue

                url = f"https://www.pinterest.com/pin/{pin_id}/"

                if url not in seen:
                    seen.add(url)
                    collected_urls.append(url)

        page.on("response", handle_response)

        try:

            logger.info(f"[{keyword}] starting")

            url = f"https://www.pinterest.com/search/pins/?q={keyword}"

            response = await page.goto(
                url,
                timeout=60000,
                wait_until="domcontentloaded"
            )

            if response and not response.ok:
                raise Exception(f"Pinterest error {response.status}")

            await asyncio.sleep(random.uniform(3, 5))

            last_height = await self._get_height(page)
            same_height = 0
            scrolls = 0
            first_scroll_done = False

            while scrolls < MAX_SCROLLS_PER_PAGE:

                if self._should_stop():
                    logger.info(f"[{keyword}] stopped by user")
                    break

                await self._extract_dom(page, collected_urls, seen)

                await page.evaluate(
                    "window.scrollBy(0, Math.floor(Math.random()*1200)+800)"
                )

                await asyncio.sleep(random.uniform(*SCROLL_PAUSE_RANGE))

                new_height = await self._get_height(page)

                if new_height == last_height:
                    same_height += 1
                else:
                    same_height = 0
                    last_height = new_height

                scrolls += 1

                if same_height >= MAX_SAME_HEIGHT:
                    logger.info(f"[{keyword}] scroll finished")
                    break

                if scrolls % 10 == 0:
                    logger.info(
                        f"[{keyword}] scroll {scrolls} pins {len(collected_urls)}"
                    )

            logger.success(
                f"[{keyword}] collected {len(collected_urls)} pins"
            )

        except Exception as e:
            logger.error(f"[{keyword}] error {e}")
            raise

        finally:

            try:
                page.remove_listener("response", handle_response)
            except Exception:
                pass

            try:
                await page.close()
            except Exception:
                pass

        return collected_urls

    async def _extract_dom(self, page, bucket, seen):

        try:

            links = await page.evaluate(
                """
                () => Array.from(
                    document.querySelectorAll("a[href^='/pin/']")
                ).map(a => a.getAttribute("href"))
                """
            )

            for href in links:

                normalized = self._normalize_pin_url(href)

                if normalized and normalized not in seen:
                    seen.add(normalized)
                    bucket.append(normalized)

        except PlaywrightError:
            pass

    async def _get_height(self, page):

        try:
            return await page.evaluate("document.body.scrollHeight")
        except PlaywrightError:
            return None

    @staticmethod
    def _normalize_pin_url(href: str):

        parsed = urlparse(href)

        parts = parsed.path.strip("/").split("/")

        if len(parts) >= 2 and parts[0] == "pin":
            return f"https://www.pinterest.com/pin/{parts[1]}/"

        return None

    def _should_stop(self):

        return cache.get(f"stop_task_{self.task.id}") is True