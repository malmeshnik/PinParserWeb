import json
import re
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI, RateLimitError
from loguru import logger

from apps.uniqueness.models import UniquenessConfig
from apps.results.models import PinResult


class AIUniquenessService:
    def __init__(self, config: UniquenessConfig):
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)

        self.timestamps = deque()
        self.lock = threading.Lock()

    def process_queryset(self, queryset):
        with ThreadPoolExecutor(
            max_workers=self.config.max_workers
        ) as executor:

            futures = {
                executor.submit(self._process_one, pin): pin.id
                for pin in queryset
            }

            for future in as_completed(futures):
                pin_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.warning(
                        f"[UNIQUENESS] pin {pin_id} failed | {e}"
                    )

    def _process_one(self, pin: PinResult):
        prompt = self._build_prompt(pin)
        content = self._call_api(prompt)

        if not content:
            return

        try:
            match = re.search(r"\{.*\}", content, re.S)

            if not match:
                raise ValueError("No JSON found")
            
            logger.info(f'Find json answer {match}')
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
                time.sleep(backoff)
                backoff *= 2
            except Exception:
                time.sleep(backoff)
                backoff *= 2

        return ""

    def _throttle(self):
        with self.lock:
            now = time.time()
            while self.timestamps and self.timestamps[0] <= now - 60:
                self.timestamps.popleft()

            if len(self.timestamps) >= self.config.max_requests_per_minute:
                wait = 60 - (now - self.timestamps[0])
                time.sleep(max(wait, 0))

            self.timestamps.append(time.time())
