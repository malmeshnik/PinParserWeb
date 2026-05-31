import random
from loguru import logger
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


class BrowserFactory:
    def __init__(self, account, headless=True):
        self.account = account
        self.proxy = account.proxy
        self.headless = headless
        self.user_agent = account.user_agent

    async def launch(self):
        from apps.proxies.nine_proxy import NineProxyService

        # 🔥 нормальний UA
        if not self.user_agent or "Firefox" in self.user_agent:
            self.user_agent = random.choice(USER_AGENTS)
            self.account.user_agent = self.user_agent
            await sync_to_async(self.account.save)(update_fields=['user_agent'])

        playwright = await async_playwright().start()

        launch_kwargs = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--start-maximized",
            ]
        }

        current_proxy = self.proxy

        if current_proxy:
            proxy_url = None

            if current_proxy.is_9proxy:
                nine_proxy = NineProxyService()

                filters = {
                    "country": current_proxy.country,
                    "state": current_proxy.state,
                    "city": current_proxy.city,
                    "zip": current_proxy.zip,
                    "isp": current_proxy.isp,
                }

                proxy = await sync_to_async(nine_proxy.get_proxy)(
                    current_proxy, filters=filters
                )

                if proxy:
                    proxy_url = f"http://{proxy.host}:{proxy.port}"
                    launch_kwargs["proxy"] = {
                        "server": proxy_url,
                    }

                    logger.info(f"Using 9Proxy: {proxy_url}")

            else:
                proxy_url = f"http://{current_proxy.host}:{current_proxy.port}"

                launch_kwargs["proxy"] = {
                    "server": proxy_url,
                    "username": current_proxy.username,
                    "password": current_proxy.password,
                }

        logger.info(
            f"Launching browser | UA={self.user_agent} | Proxy={current_proxy}"
        )

        browser = await playwright.chromium.launch(**launch_kwargs)

        context = await browser.new_context(
            user_agent=self.user_agent,
            viewport=None,  # 👈 важливо
            locale="en-US",
            timezone_id="America/New_York",
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            window.chrome = {
                runtime: {}
            };

            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            """)

        if self.account.cookies:
            await context.add_cookies(self.account.cookies)

        page = await context.new_page()
        await page.goto("https://www.pinterest.com/", timeout=30000)
        await page.wait_for_timeout(random.randint(3000, 6000))
        await page.close()

        return playwright, browser, context