import json
import re
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.cache import cache
from openai import OpenAI, RateLimitError
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.results.models import PinResult
from apps.tasks.models import ParseTask


class AIUniquenessService:
    def __init__(self, task: ParseTask, config: UniquenessConfig):
        self.task = task
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)

        self.timestamps = deque()
        self.lock = threading.Lock()

        self.stop_event = threading.Event()

    def process_queryset(self, queryset):
        executor = ThreadPoolExecutor(
            max_workers=self.config.max_workers
        )

        futures = {
            executor.submit(self._process_one, pin): pin.id
            for pin in queryset
        }

        try:
            for future in as_completed(futures):

                if self._should_stop():
                    logger.info("Stopping by user request")

                    self.stop_event.set()
                    executor.shutdown(wait=False, cancel_futures=True)
                    return  # 🔥 важливо!

                pin_id = futures[future]

                try:
                    future.result()
                except Exception as e:
                    logger.warning(
                        f"[UNIQUENESS] pin {pin_id} failed | {e}"
                    )

        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _process_one(self, pin: PinResult):

        if self.stop_event.is_set():
            return

        prompt = self._build_prompt(pin)
        content = self._call_api(prompt)

        if self.stop_event.is_set():
            return

        if not content:
            return

        try:
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                raise ValueError("No JSON found")

            data = json.loads(match.group())

            pin.utitle = data.get("title")
            pin.udescription = data.get("description")
            pin.save(update_fields=["utitle", "udescription"])

        except json.JSONDecodeError:
            logger.warning(
                f"[UNIQUENESS] Invalid JSON for pin {pin.id}"
            )

    def _build_prompt(self, pin: PinResult) -> str:
        ctx = {}

        if self.config.use_title:
            ctx["title"] = pin.title or ""
        if self.config.use_description:
            ctx["description"] = pin.description or ""
        if self.config.use_alt_text:
            ctx["alt_text"] = pin.alt_text or ""
        if self.config.use_annotation:
            ctx["annotation"] = pin.annotation or ""
        if self.config.use_domain:
            ctx["domain"] = pin.domain or ""
        if self.config.use_image_url:
            ctx["image_url"] = pin.image_url or ""
        if self.config.use_keyword:
            ctx["keyword"] = pin.keyword or ""

        prompt = self.config.prompt_template
        for k, v in ctx.items():
            prompt = prompt.replace(f"{{{{{k}}}}}", v)

        return prompt

    def _call_api(self, prompt: str) -> str:
        backoff = 1.0

        for _ in range(5):

            if self.stop_event.is_set():
                return ""

            self._throttle()

            try:
                resp = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.temperature,
                    max_tokens=(
                        self.config.max_tokens_title
                        + self.config.max_tokens_description
                    ),
                )

                return resp.choices[0].message.content.strip()

            except RateLimitError:
                if not self._interruptible_sleep(backoff):
                    return ""
                backoff *= 2

            except Exception:
                if not self._interruptible_sleep(backoff):
                    return ""
                backoff *= 2

        return ""

    def _throttle(self):
        with self.lock:
            now = time.time()

            while self.timestamps and self.timestamps[0] <= now - 60:
                self.timestamps.popleft()

            if len(self.timestamps) >= self.config.max_requests_per_minute:
                wait = 60 - (now - self.timestamps[0])
                if not self._interruptible_sleep(wait):
                    return

            self.timestamps.append(time.time())

    def _interruptible_sleep(self, seconds: float) -> bool:
        end_time = time.time() + seconds

        while time.time() < end_time:
            if self.stop_event.is_set():
                return False
            time.sleep(0.1)

        return True

    def _should_stop(self) -> bool:
        if cache.get(f"stop_task_{self.task.id}") is True:
            self.stop_event.set()
            return True
        return False