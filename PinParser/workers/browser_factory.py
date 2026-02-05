import random
from loguru import logger
from playwright.async_api import async_playwright

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


class BrowserFactory:
    def __init__(self, account, headless=True):
        self.account = account
        self.proxy = account.proxy
        self.headless = headless
        self.user_agent = random.choice(USER_AGENTS)

    async def launch(self):
        playwright = await async_playwright().start()

        launch_kwargs = {
            "headless": self.headless,
        }

        if self.proxy:
            launch_kwargs["proxy"] = {
                "server": f"http://{self.proxy.host}:{self.proxy.port}",
            }

        logger.info(
            f"Launching browser | UA={self.user_agent} | Proxy={self.proxy}"
        )

        browser = await playwright.chromium.launch(**launch_kwargs)

        context = await browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 800},
        )

        if self.account.cookies:
            await context.add_cookies(self.account.cookies)

        return playwright, browser, context
