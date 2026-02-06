import random
from loguru import logger
from playwright.async_api import async_playwright

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
]


class BrowserFactory:
    def __init__(self, account, headless=True):
        self.account = account
        self.proxy = account.proxy
        self.headless = headless

        # Use account's UA if set, otherwise pick random and save it to account
        if account.user_agent:
            self.user_agent = account.user_agent
        else:
            self.user_agent = random.choice(USER_AGENTS)
            account.user_agent = self.user_agent
            account.save(update_fields=['user_agent'])

    async def launch(self):
        from apps.proxies.nine_proxy import NineProxyService

        playwright = await async_playwright().start()

        launch_kwargs = {
            "headless": self.headless,
        }

        current_proxy = self.proxy
        # If no proxy assigned to account, try to get one from 9Proxy
        if not current_proxy:
            nine_proxy = NineProxyService()
            current_proxy = nine_proxy.get_and_create_proxy_model()
            if current_proxy:
                logger.info(f"Got proxy from 9Proxy: {current_proxy.host}:{current_proxy.port}")

        if current_proxy:
            launch_kwargs["proxy"] = {
                "server": f"http://{current_proxy.host}:{current_proxy.port}",
            }

        logger.info(
            f"Launching browser | UA={self.user_agent} | Proxy={current_proxy}"
        )

        browser = await playwright.chromium.launch(**launch_kwargs)

        context = await browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 800},
        )

        if self.account.cookies:
            await context.add_cookies(self.account.cookies)

        return playwright, browser, context
