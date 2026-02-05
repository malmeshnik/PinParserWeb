import random
import time
from typing import Optional

import requests
from loguru import logger
from requests import Response

from apps.proxies.models import Proxy

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) "
    "Gecko/20100101 Firefox/118.0",
]

class PinFetcher:
    def __init__(
        self,
        proxy: Optional[Proxy] = None,
        cookies: Optional[list[dict]] = None,
        timeout: int = 20,
        max_retries: int = 3,
        delay_range: tuple[float, float] = (1.0, 3.0),
    ):
        self.proxy = proxy
        self.cookies = cookies or []
        self.timeout = timeout
        self.max_retries = max_retries
        self.delay_range = delay_range

        self.session = requests.Session()
        self._prepare_session()

    def fetch(self, pin_url: str) -> Optional[str]:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    pin_url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )

                if self._is_valid_response(response):
                    return response.text

                logger.warning(
                    f"[PIN FETCH] Bad response "
                    f"{response.status_code} | {pin_url}"
                )

            except requests.RequestException as e:
                logger.warning(
                    f"[PIN FETCH] Attempt {attempt} failed | {e}"
                )

            time.sleep(random.uniform(*self.delay_range))

        logger.error(f"[PIN FETCH] Failed after retries | {pin_url}")
        return None
    
    def _prepare_session(self):
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/webp,*/*;q=0.8"
            ),
            "Connection": "keep-alive",
        })

        for cookie in self.cookies:
            try:
                self.session.cookies.set(
                    name=cookie.get("name"),
                    value=cookie.get("value"),
                    domain=cookie.get("domain"),
                    path=cookie.get("path", "/"),
                )
            except Exception:
                continue

        if self.proxy:
            proxy_url = f"http://{self.proxy.host}:{self.proxy.port}"
            self.session.proxies.update({
                "http": proxy_url,
                "https": proxy_url,
            })
            logger.info(f"[PIN FETCH] Using proxy {proxy_url}")

    def _is_valid_response(self, response: Response) -> bool:
        if response.status_code != 200:
            return False

        text = response.text.lower()

        if "__pws_relay_register_completed_request__" in text:
            return True

        if "pinterest" in text and "<html" in text:
            return True

        return False