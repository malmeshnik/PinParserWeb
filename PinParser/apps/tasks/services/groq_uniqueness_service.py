import re
import json
import requests
import time
import random
from typing import Optional, Dict
from loguru import logger


class GroqUniquenessService:
    """Сервіс для унікалізації контенту через Groq API"""

    def __init__(self, api_key: str, prompt_template: str):
        self.api_key = api_key
        self.prompt_template = prompt_template
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"

    def uniquify(
        self,
        title: str,
        description: str,
        alt_text: str = "",
        annotation: str = "",
        max_retries: int = 3,
    ) -> Optional[Dict[str, str]]:
        """
        Унікалізує title та description через Groq API

        Args:
            title: Оригінальний заголовок
            description: Оригінальний опис
            alt_text: Alt текст
            annotation: Анотація
            max_retries: Кількість спроб при помилках

        Returns:
            Dict з ключами 'title' та 'description' або None якщо всі спроби невдалі
        """
        if not self.api_key or not self.api_key.strip():
            logger.error("[GROQ] API ключ не вказано")
            return None

        final_prompt = self.prompt_template.replace("{{title}}", title or "")
        final_prompt = final_prompt.replace("{{description}}", description or "")
        final_prompt = final_prompt.replace("{{alt_text}}", alt_text or "")
        final_prompt = final_prompt.replace("{{annotation}}", annotation or "")
        final_prompt += "\n\nOutput must be a valid JSON object."

        payload = {
            "model": "qwen/qwen3.6-27b",
            "messages": [
                {
                    "role": "user",
                    "content": final_prompt
                }
            ],
            "temperature": 0.5,
            "response_format": {"type": "json_object"}
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

                # Rate limit — більше НЕ чекаємо, одразу здаємось
                if response.status_code == 429:
                    logger.warning(
                        f"[GROQ] Rate limit (спроба {attempt}/{max_retries}), пропускаємо без очікування"
                    )
                    last_error = f"429: {response.text}"
                    return None

                # Серверні помилки — короткий backoff (макс ~2с), не десятки хвилин
                if response.status_code >= 500:
                    wait_time = self._backoff_delay(attempt)
                    logger.warning(
                        f"[GROQ] Серверна помилка {response.status_code} (спроба {attempt}/{max_retries}), "
                        f"чекаємо {wait_time:.1f}с"
                    )
                    last_error = f"{response.status_code}: {response.text}"
                    time.sleep(wait_time)
                    continue

                # Клієнтські помилки (400, 401, 403 тощо) — повторювати сенсу немає
                if response.status_code != 200:
                    logger.error(
                        f"[GROQ] Помилка API: {response.status_code} | {response.text}"
                    )
                    return None

                # Статус 200 — парсимо відповідь
                res_data = response.json()
                content = res_data["choices"][0]["message"]["content"].strip()

                match = re.search(r'\{[\s\S]*\}', content)
                result = json.loads(match.group(0)) if match else json.loads(content)

                if "title" in result and "description" in result:
                    logger.success(f"[GROQ] Успішно унікалізовано (спроба {attempt})")
                    return {
                        "title": result["title"],
                        "description": result["description"]
                    }
                else:
                    logger.warning(
                        f"[GROQ] Відповідь не містить title/description (спроба {attempt}/{max_retries})"
                    )
                    last_error = "missing title/description in response"
                    time.sleep(self._backoff_delay(attempt))
                    continue

            except requests.Timeout as e:
                last_error = f"timeout: {e}"
                wait_time = self._backoff_delay(attempt)
                logger.warning(
                    f"[GROQ] Таймаут (спроба {attempt}/{max_retries}), чекаємо {wait_time:.1f}с"
                )
                time.sleep(wait_time)
                continue

            except requests.RequestException as e:
                last_error = f"network error: {e}"
                wait_time = self._backoff_delay(attempt)
                logger.warning(
                    f"[GROQ] Помилка мережі (спроба {attempt}/{max_retries}): {e}, чекаємо {wait_time:.1f}с"
                )
                time.sleep(wait_time)
                continue

            except json.JSONDecodeError as e:
                last_error = f"json decode error: {e}"
                logger.warning(
                    f"[GROQ] Помилка парсингу JSON (спроба {attempt}/{max_retries}): {e}"
                )
                time.sleep(self._backoff_delay(attempt))
                continue

            except Exception as e:
                last_error = f"unexpected error: {e}"
                logger.error(f"[GROQ] Критична помилка (спроба {attempt}/{max_retries}): {e}")
                time.sleep(self._backoff_delay(attempt))
                continue

        logger.error(f"[GROQ] Всі {max_retries} спроб вичерпано. Остання помилка: {last_error}")
        return None

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        """Коротка експоненційна затримка з jitter: ~1с, 2с (макс 2с)"""
        base = min(2 ** (attempt - 1), 2)
        return base + random.uniform(0, 0.5)

    @staticmethod
    def generate_slug(text: str) -> str:
        """Генерує slug з тексту (як в Google Apps Script)"""
        if not text:
            return ""

        import unicodedata

        text = text.lower()
        text = unicodedata.normalize('NFD', text)
        text = re.sub(r'[̀-ͯ]', '', text)
        text = text.replace('đ', 'd').replace('Đ', 'd')
        text = re.sub(r'[^a-z0-9\s-]', '', text)
        text = text.strip()
        text = re.sub(r'\s+', '-', text)
        text = re.sub(r'-+', '-', text)

        return text