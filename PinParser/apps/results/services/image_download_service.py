import os
import time
import random
import hashlib
from typing import Optional
from io import BytesIO

import requests
from django.core.files.base import ContentFile
from loguru import logger


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) "
    "Gecko/20100101 Firefox/118.0",
]


class ImageDownloadService:
    def __init__(
        self,
        timeout: int = 15,
        max_retries: int = 2,
        delay_range: tuple[float, float] = (0.5, 1.5),
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.delay_range = delay_range

    def download_image(self, image_url: str, pin_id: str) -> Optional[ContentFile]:
        """
        Завантажує фото з image_url та повертає ContentFile для збереження в ImageField

        Args:
            image_url: URL фото для завантаження
            pin_id: ID піна для формування імені файлу

        Returns:
            ContentFile з фото або None якщо не вдалося завантажити
        """
        if not image_url:
            return None

        for attempt in range(1, self.max_retries + 1):
            try:
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.pinterest.com/",
                }

                response = requests.get(
                    image_url,
                    headers=headers,
                    timeout=self.timeout,
                    stream=True,
                )

                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', '')

                    if 'image' not in content_type:
                        logger.warning(
                            f"[IMAGE DOWNLOAD] Not an image: {content_type} | {image_url}"
                        )
                        return None

                    image_data = response.content

                    if len(image_data) < 1024:
                        logger.warning(
                            f"[IMAGE DOWNLOAD] Image too small ({len(image_data)} bytes) | {image_url}"
                        )
                        return None

                    ext = self._get_extension(content_type, image_url)
                    filename = f"{pin_id}{ext}"

                    logger.success(
                        f"[IMAGE DOWNLOAD] Downloaded {len(image_data)} bytes | {filename}"
                    )

                    return ContentFile(image_data, name=filename)

                else:
                    logger.warning(
                        f"[IMAGE DOWNLOAD] HTTP {response.status_code} | {image_url}"
                    )

            except requests.RequestException as e:
                logger.warning(
                    f"[IMAGE DOWNLOAD] Attempt {attempt}/{self.max_retries} failed | {e}"
                )

            if attempt < self.max_retries:
                time.sleep(random.uniform(*self.delay_range))

        logger.error(f"[IMAGE DOWNLOAD] Failed after {self.max_retries} retries | {image_url}")
        return None

    def _get_extension(self, content_type: str, url: str) -> str:
        """Визначає розширення файлу з Content-Type або URL"""

        content_type_map = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp',
        }

        ext = content_type_map.get(content_type.lower())
        if ext:
            return ext

        if url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            return os.path.splitext(url)[1].lower()

        return '.jpg'
