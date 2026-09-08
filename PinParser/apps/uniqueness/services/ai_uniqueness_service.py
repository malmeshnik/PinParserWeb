import json
import re
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.cache import cache
from django.db import connection
from openai import OpenAI, RateLimitError, APIError, AuthenticationError
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.results.models import PinResult
from apps.tasks.models import ParseTask


class AIUniquenessService:
    def __init__(self, task: ParseTask, config: UniquenessConfig):
        self.task = task
        self.config = config

        # Ініціалізуємо клієнт OpenAI з автоматичним base_url
        client_kwargs = {"api_key": config.openai_api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url

        self.client = OpenAI(**client_kwargs)

        self.timestamps = deque()
        self.lock = threading.Lock()

        self.stop_event = threading.Event()

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

        for attempt in range(1, max_retries + 1):

            if self.stop_event.is_set():
                return ""

            self._throttle()

            try:
                max_tokens_value = (
                    self.config.max_tokens_title
                    + self.config.max_tokens_description
                )

                # GPT-5, GPT-4.1, and GPT-4o models use max_completion_tokens
                # Older models and Qwen use max_tokens
                if self.config.model.startswith(('gpt-5', 'gpt-4.1', 'gpt-4o')):
                    resp = self.client.chat.completions.create(
                        model=self.config.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.config.temperature,
                        max_completion_tokens=max_tokens_value,
                    )
                else:
                    resp = self.client.chat.completions.create(
                        model=self.config.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.config.temperature,
                        max_tokens=max_tokens_value,
                    )

                return resp.choices[0].message.content.strip()

            except AuthenticationError as e:
                # 403 Forbidden - API key issue, don't retry
                self.stats["auth_errors"] += 1
                logger.error(
                    f"[UNIQUENESS] Pin {pin_id} - Authentication error (403): {e}\n"
                    f"Check API key for provider: {self.config.model_provider}"
                )
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