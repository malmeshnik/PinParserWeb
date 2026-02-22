import random
from django.core.cache import cache
import time
from typing import Optional
from asgiref.sync import sync_to_async

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
        account,
        task=None,
        timeout: int = 20,
        max_retries: int = 2,
        delay_range: tuple[float, float] = (1.0, 3.0),
    ):
        self.account = account
        self.task = task
        self.timeout = timeout
        self.max_retries = max_retries
        self.delay_range = delay_range
        self.session = requests.Session()
        self._prepare_session()

    def fetch(self, pin_url: str) -> Optional[str]:
        last_response = None
        for attempt in range(1, self.max_retries + 1):
            try:
                
                response = self.session.get(
                    pin_url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                last_response = response

                if self._is_valid_response(response):
                    return response.text

                if response.status_code == 403 or response.status_code == 429:
                    logger.warning(f"[PIN FETCH] Blocked ({response.status_code}). Rotating UA/Proxy/Cookie...")
                    self._rotate_everything()

                logger.warning(
                    f"[PIN FETCH] Bad response "
                    f"{response.status_code} | {pin_url}"
                )

            except requests.RequestException as e:
                logger.warning(
                    f"[PIN FETCH] Attempt {attempt} failed | {e}"
                )
                self._rotate_everything()

            time.sleep(random.uniform(*self.delay_range))

        error_msg = f"[PIN FETCH] Failed after retries | {pin_url}"
        logger.error(error_msg)
        self._log_to_db(error_msg)

        if self.account:
            # If it's a block (403, 429) or a connection error (no last_response), increment fail count
            if last_response is None or last_response.status_code in [403, 429]:
                self.account.register_fail()

        return None

    def _log_to_db(self, message):
        if self.task:
            from apps.logs.models import ErrorLog
            ErrorLog.objects.create(
                task=self.task,
                account=self.account,
                message=message[:5000]
            )

    def _rotate_everything(self):
        new_ua = random.choice(USER_AGENTS)
        self.session.headers.update({"User-Agent": new_ua})
        if self.account:
            self.account.user_agent = new_ua
            self.account.save(update_fields=['user_agent'])

    def _prepare_session(self):
        ua = self.account.user_agent if self.account and self.account.user_agent else random.choice(USER_AGENTS)

        self.session.headers.update({
            "User-Agent": ua,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/webp,*/*;q=0.8"
            ),
            "Connection": "keep-alive",
        })


    def _is_valid_response(self, response: Response) -> bool:
        if response.status_code != 200:
            return False

        text = response.text.lower()

        if "__pws_relay_register_completed_request__" in text:
            return True

        if "pinterest" in text and "<html" in text:
            return True

        return False
        
    def _should_stop(self) -> bool:
        return cache.get(f"stop_task_{self.task.id}") is True
