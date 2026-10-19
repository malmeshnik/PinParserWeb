import json
import re
import time
import threading
from collections import deque
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import (
    OpenAI,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    BadRequestError,
)
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.results.models import PinResult
from apps.tasks.models import ParseTask
from apps.tasks.services.task_control import is_stop_requested

# Помилки конфігурації (ключ, доступ, модель, параметри) — повторювати запит немає сенсу
NON_RETRYABLE_ERRORS = (AuthenticationError, PermissionDeniedError, NotFoundError, BadRequestError)


@dataclass
class UniquenessResult:
    succeeded: int = 0
    failed: int = 0
    last_error: str | None = None
    fatal_error: str | None = None
    stopped: bool = False


class AIUniquenessService:
    def __init__(self, task: ParseTask, config: UniquenessConfig):
        self.task = task
        self.config = config

        # Ініціалізація клієнта в залежності від методу унікалізації
        if config.uniqueness_method == 'omniroute':
            self.client = OpenAI(
                api_key=config.omniroute_api_key,
                base_url=config.omniroute_base_url
            )
            self.model = config.omniroute_model
        else:  # gpt
            self.client = OpenAI(api_key=config.openai_api_key)
            self.model = config.model

        self.timestamps = deque()
        self.lock = threading.Lock()

        self.stop_event = threading.Event()
        self.fatal_error = None

    def process_queryset(self, queryset) -> UniquenessResult:
        result = UniquenessResult()
        executor = ThreadPoolExecutor(
            max_workers=max(1, self.config.max_workers)
        )

        futures = {
            executor.submit(self._process_one, pin): pin.id
            for pin in queryset
        }

        try:
            for future in as_completed(futures):

                if self._should_stop():
                    logger.info("Stopping by user request")
                    result.stopped = True
                    return result

                pin_id = futures[future]

                try:
                    future.result()
                    result.succeeded += 1
                except Exception as e:
                    result.failed += 1
                    result.last_error = str(e)
                    logger.warning(
                        f"[UNIQUENESS] pin {pin_id} failed | {e}"
                    )

                if self.fatal_error:
                    # Невірний ключ/модель — решта запитів теж впаде, зупиняємось одразу
                    result.fatal_error = self.fatal_error
                    return result

        finally:
            self.stop_event.set()
            executor.shutdown(wait=False, cancel_futures=True)

        return result

    def _process_one(self, pin: PinResult):
        if self.stop_event.is_set():
            raise RuntimeError("Обробку перервано")

        content = self._call_api(self._build_prompt(pin))

        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ValueError("No JSON found in response")

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in response: {e}")

        if not data.get("title"):
            raise ValueError("Response has no 'title'")

        pin.utitle = data["title"]
        pin.udescription = data.get("description")
        pin.save(update_fields=["utitle", "udescription"])

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
        last_error = None

        for _ in range(5):

            if self.stop_event.is_set():
                raise RuntimeError("Обробку перервано")

            self._throttle()

            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.temperature,
                    max_tokens=(
                        self.config.max_tokens_title
                        + self.config.max_tokens_description
                    ),
                )

                content = resp.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from API")
                return content.strip()

            except NON_RETRYABLE_ERRORS as e:
                self.fatal_error = str(e)
                self.stop_event.set()
                raise

            except Exception as e:
                last_error = e
                if not self._interruptible_sleep(backoff):
                    break
                backoff *= 2

        raise RuntimeError(f"API request failed after retries: {last_error}")

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
        if is_stop_requested(self.task.id):
            self.stop_event.set()
            return True
        return False
