import json
import re
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.cache import cache
from django.db import connection
from openai import (
    OpenAI,
    RateLimitError,
    APIError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
)
from loguru import logger

from apps.uniqueness.models import UniquenessConfig, ModelProvider
from apps.results.models import PinResult
from apps.tasks.models import ParseTask

# Reasoning-моделі витрачають частину completion-токенів на міркування,
# тому без запасу відповідь може повернутися порожньою
REASONING_TOKENS_HEADROOM = 2000

# Скільки разів можна підлаштувати параметри запиту під модель за один виклик
MAX_PARAM_ADAPTATIONS = 3


class AIUniquenessService:
    def __init__(self, task: ParseTask, config: UniquenessConfig):
        self.task = task
        self.config = config

        # Ініціалізуємо клієнт OpenAI з автоматичним base_url
        config.clean()
        client_kwargs = {"api_key": config.api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url

        self.client = OpenAI(**client_kwargs)

        self.timestamps = deque()
        self.lock = threading.Lock()

        self.stop_event = threading.Event()

        # Параметри спільні для всіх потоків: якщо модель відхилить якийсь параметр,
        # виправлення одразу підхоплять наступні запити
        self.request_params = self._build_request_params()
        self.params_lock = threading.Lock()

        # Помилка, через яку немає сенсу продовжувати (невірний ключ, модель недоступна)
        self.fatal_error = None

        # Tracking statistics
        self.stats = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "auth_errors": 0,
            "rate_limit_errors": 0,
            "api_errors": 0,
        }
        self.failed_pin_ids = []

    def process_queryset(self, queryset):
        total_count = queryset.count()
        logger.info(f"[UNIQUENESS] Starting processing {total_count} pins for task {self.task.id}")

        executor = ThreadPoolExecutor(
            max_workers=self.config.max_workers
        )

        futures = {
            executor.submit(self._process_one_with_cleanup, pin): pin.id
            for pin in queryset
        }

        try:
            for future in as_completed(futures):

                if self._should_stop():
                    logger.info(f"[UNIQUENESS] Stopping by user request. Stats: {self.stats}")

                    self.stop_event.set()
                    executor.shutdown(wait=False, cancel_futures=True)
                    return

                if self.fatal_error:
                    logger.error(
                        f"[UNIQUENESS] Aborting task {self.task.id}: {self.fatal_error}. Stats: {self.stats}"
                    )
                    executor.shutdown(wait=False, cancel_futures=True)
                    return

                pin_id = futures[future]
                self.stats["processed"] += 1

                try:
                    result = future.result()
                    if result:
                        self.stats["success"] += 1
                    else:
                        self.stats["failed"] += 1
                        self.failed_pin_ids.append(pin_id)

                    # Log progress every 10 pins
                    if self.stats["processed"] % 10 == 0:
                        logger.info(
                            f"[UNIQUENESS] Progress: {self.stats['processed']}/{total_count} | "
                            f"Success: {self.stats['success']} | Failed: {self.stats['failed']}"
                        )

                except Exception as e:
                    self.stats["failed"] += 1
                    self.failed_pin_ids.append(pin_id)
                    logger.error(
                        f"[UNIQUENESS] pin {pin_id} failed with exception | {type(e).__name__}: {e}"
                    )

        finally:
            executor.shutdown(wait=False, cancel_futures=True)

            # Final statistics
            logger.info(
                f"[UNIQUENESS] Task {self.task.id} completed. Final stats:\n"
                f"  Total processed: {self.stats['processed']}\n"
                f"  Success: {self.stats['success']}\n"
                f"  Failed: {self.stats['failed']}\n"
                f"  Auth errors: {self.stats['auth_errors']}\n"
                f"  Rate limit errors: {self.stats['rate_limit_errors']}\n"
                f"  API errors: {self.stats['api_errors']}"
            )

            if self.failed_pin_ids:
                logger.warning(
                    f"[UNIQUENESS] {len(self.failed_pin_ids)} pins failed processing. IDs: {self.failed_pin_ids[:20]}"
                    + ("..." if len(self.failed_pin_ids) > 20 else "")
                )

    def _process_one_with_cleanup(self, pin: PinResult) -> bool:
        """Wrapper that ensures DB connection is closed after processing."""
        try:
            return self._process_one(pin)
        finally:
            # Close database connection for this thread to prevent leak
            connection.close()

    def _process_one(self, pin: PinResult) -> bool:
        """Process single pin. Returns True on success, False on failure."""

        if self.stop_event.is_set():
            self.stats["skipped"] += 1
            return False

        prompt = self._build_prompt(pin)
        content = self._call_api(prompt, pin.id)

        if self.stop_event.is_set():
            self.stats["skipped"] += 1
            return False

        if not content:
            logger.error(f"[UNIQUENESS] Pin {pin.id} - API returned empty content")
            return False

        try:
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                logger.error(f"[UNIQUENESS] Pin {pin.id} - No JSON found in response: {content[:200]}")
                raise ValueError("No JSON found")

            data = json.loads(match.group())

            pin.utitle = data.get("title")
            pin.udescription = data.get("description")
            pin.save(update_fields=["utitle", "udescription"])

            logger.debug(f"[UNIQUENESS] Pin {pin.id} processed successfully")
            return True

        except json.JSONDecodeError as e:
            logger.error(
                f"[UNIQUENESS] Pin {pin.id} - Invalid JSON: {e}\n"
                f"Content: {content[:500]}"
            )
            return False
        except Exception as e:
            logger.error(f"[UNIQUENESS] Pin {pin.id} - Unexpected error: {type(e).__name__}: {e}")
            return False

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

    def _call_api(self, prompt: str, pin_id: int) -> str:
        """Call API with exponential backoff and proper error handling."""
        backoff = 2.0  # Start with 2 seconds
        max_retries = 5
        attempt = 0
        adaptations = 0

        while attempt < max_retries:
            attempt += 1

            if self.stop_event.is_set():
                return ""

            self._throttle()

            try:
                with self.params_lock:
                    params = dict(self.request_params)

                resp = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[{"role": "user", "content": prompt}],
                    **params,
                )

                choice = resp.choices[0]
                content = (choice.message.content or "").strip()
                if not content:
                    logger.warning(
                        f"[UNIQUENESS] Pin {pin_id} - Empty response "
                        f"(finish_reason={choice.finish_reason}, model={self.config.model})"
                    )
                return content

            except AuthenticationError as e:
                # 401 - API key issue, all other pins will fail too
                self.stats["auth_errors"] += 1
                self._abort(
                    f"Помилка авторизації API ({self.config.model_provider}), перевірте ключ: {e}"
                )
                return ""

            except (NotFoundError, PermissionDeniedError) as e:
                # Model doesn't exist or isn't available for this API key
                self.stats["api_errors"] += 1
                self._abort(f"Модель '{self.config.model}' недоступна: {e}")
                return ""

            except BadRequestError as e:
                if adaptations < MAX_PARAM_ADAPTATIONS and self._adapt_params(e):
                    adaptations += 1
                    # The request was rejected before generation, don't count it as an attempt
                    attempt -= 1
                    continue

                # Other 400 errors won't be fixed by retrying the same request
                self.stats["api_errors"] += 1
                logger.error(f"[UNIQUENESS] Pin {pin_id} - Bad request (400): {e}")
                return ""

            except RateLimitError as e:
                # 429 Too Many Requests
                self.stats["rate_limit_errors"] += 1
                if attempt < max_retries:
                    wait_time = backoff * attempt
                    logger.warning(
                        f"[UNIQUENESS] Pin {pin_id} - Rate limit hit. "
                        f"Retry {attempt}/{max_retries} after {wait_time:.1f}s"
                    )
                    if not self._interruptible_sleep(wait_time):
                        return ""
                else:
                    logger.error(f"[UNIQUENESS] Pin {pin_id} - Rate limit exceeded after {max_retries} retries")
                    return ""

            except APIError as e:
                # Other API errors (500, etc)
                self.stats["api_errors"] += 1
                status_code = getattr(e, 'status_code', 'unknown')

                if attempt < max_retries:
                    wait_time = backoff * attempt
                    logger.warning(
                        f"[UNIQUENESS] Pin {pin_id} - API error (status {status_code}): {e}\n"
                        f"Retry {attempt}/{max_retries} after {wait_time:.1f}s"
                    )
                    if not self._interruptible_sleep(wait_time):
                        return ""
                else:
                    logger.error(
                        f"[UNIQUENESS] Pin {pin_id} - API error persisted after {max_retries} retries. "
                        f"Status: {status_code}, Error: {e}"
                    )
                    return ""

            except Exception as e:
                # Unexpected errors
                logger.error(
                    f"[UNIQUENESS] Pin {pin_id} - Unexpected error on attempt {attempt}/{max_retries}: "
                    f"{type(e).__name__}: {e}"
                )
                if attempt < max_retries:
                    wait_time = backoff * attempt
                    if not self._interruptible_sleep(wait_time):
                        return ""
                else:
                    return ""

        return ""

    def _build_request_params(self) -> dict:
        """Параметри запиту залежно від провайдера та сімейства моделі."""
        max_tokens_value = (
            self.config.max_tokens_title
            + self.config.max_tokens_description
        )

        if self.config.is_reasoning_model:
            # Reasoning models accept only the default temperature
            return {
                "max_completion_tokens": max_tokens_value + REASONING_TOKENS_HEADROOM,
                "reasoning_effort": "low",
            }

        if self.config.model_provider == ModelProvider.OPENAI:
            # Current OpenAI chat models use max_completion_tokens
            return {
                "temperature": self.config.temperature,
                "max_completion_tokens": max_tokens_value,
            }

        # Qwen and OmniRoute use max_tokens
        return {
            "temperature": self.config.temperature,
            "max_tokens": max_tokens_value,
        }

    def _adapt_params(self, error: BadRequestError) -> bool:
        """Підлаштовує параметри під модель, якщо вона відхилила один з них.

        Returns True, якщо запит варто повторити з оновленими параметрами.
        """
        param = error.param
        swaps = {
            "max_tokens": "max_completion_tokens",
            "max_completion_tokens": "max_tokens",
        }
        removable = ("temperature", "reasoning_effort")

        if param not in swaps and param not in removable:
            return False

        with self.params_lock:
            if param not in self.request_params:
                # Another thread already adapted this param
                return True

            if param in swaps:
                self.request_params[swaps[param]] = self.request_params.pop(param)
            else:
                self.request_params.pop(param)

            logger.warning(
                f"[UNIQUENESS] Model {self.config.model} rejected '{param}', "
                f"using params: {self.request_params}"
            )

        return True

    def _abort(self, message: str):
        """Зупиняє обробку всіх пінів через помилку, яку не виправити повторами."""
        with self.params_lock:
            if self.fatal_error is None:
                self.fatal_error = message
                logger.error(f"[UNIQUENESS] Task {self.task.id} fatal error: {message}")
        self.stop_event.set()

    def _throttle(self):
        """Throttle requests to stay within rate limits."""
        with self.lock:
            now = time.time()

            # Remove timestamps older than 60 seconds
            while self.timestamps and self.timestamps[0] <= now - 60:
                self.timestamps.popleft()

            # Check if we've hit the rate limit
            if len(self.timestamps) >= self.config.max_requests_per_minute:
                wait = 60 - (now - self.timestamps[0]) + 0.5  # Add small buffer
                logger.debug(f"[UNIQUENESS] Rate limit reached, waiting {wait:.1f}s")
                if not self._interruptible_sleep(wait):
                    return

            # Add minimum delay between requests for DashScope
            if self.timestamps:
                time_since_last = now - self.timestamps[-1]
                min_delay = self._get_min_delay_between_requests()


                if time_since_last < min_delay:
                    wait = min_delay - time_since_last
                    if not self._interruptible_sleep(wait):
                        return

            self.timestamps.append(time.time())

    def _get_min_delay_between_requests(self) -> float:
        """Get minimum delay between requests based on provider and config.

        Calculate delay to achieve target requests per minute with safety margin.
        """
        if self.config.model_provider == "dashscope":
            # For DashScope with 15000 req/min limit
            # Calculate: 60 seconds / max_requests_per_minute
            # Add 10% safety margin
            target_rps = self.config.max_requests_per_minute / 60
            return (1.0 / target_rps) * 1.1
        else:
            # OpenAI is more lenient
            return 0.01

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

    def get_stats(self) -> dict:
        """Get current processing statistics."""
        return {
            **self.stats,
            "failed_pin_ids": self.failed_pin_ids,
        }
