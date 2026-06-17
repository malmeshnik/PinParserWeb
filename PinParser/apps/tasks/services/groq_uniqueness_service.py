import re
import json
import requests
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
    ) -> Optional[Dict[str, str]]:
        """
        Унікалізує title та description через Groq API

        Args:
            title: Оригінальний заголовок
            description: Оригінальний опис
            alt_text: Alt текст
            annotation: Анотація

        Returns:
            Dict з ключами 'title' та 'description' або None якщо помилка
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
            "model": "llama-3.1-8b-instant",
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

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                res_data = response.json()
                content = res_data["choices"][0]["message"]["content"].strip()

                match = re.search(r'\{[\s\S]*\}', content)
                if match:
                    result = json.loads(match.group(0))
                else:
                    result = json.loads(content)

                if "title" in result and "description" in result:
                    logger.success("[GROQ] Успішно унікалізовано")
                    return {
                        "title": result["title"],
                        "description": result["description"]
                    }
                else:
                    logger.warning("[GROQ] Відповідь не містить title або description")
                    return None
            else:
                logger.error(
                    f"[GROQ] Помилка API: {response.status_code} | {response.text}"
                )
                return None

        except requests.RequestException as e:
            logger.error(f"[GROQ] Помилка мережі: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[GROQ] Помилка парсингу JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"[GROQ] Критична помилка: {e}")
            return None

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
