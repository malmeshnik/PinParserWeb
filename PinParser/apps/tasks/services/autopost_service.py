import random
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone
from loguru import logger

from apps.tasks.models import AutoPostConfig, AutoPostQueue, AutoPostStatus, PostQueueStatus
from apps.tasks.services.autopost_uniqueness_service import AutoPostUniquenessService


class AutoPostError(Exception):
    """Дію з автопостингом не можна виконати (повідомлення показується користувачу)."""


def start_autopost(config: AutoPostConfig):
    """Запускає автопостинг (або відновлює після паузи)."""
    from apps.tasks.tasks import initialize_autopost_queue

    if config.status == AutoPostStatus.RUNNING:
        raise AutoPostError("Автопостинг вже запущено")
    if not config.webhook_token or not config.board_name:
        raise AutoPostError("Заповніть webhook токен та назву дошки перед запуском")

    initialize_autopost_queue.delay(config.id)


def stop_autopost(config: AutoPostConfig):
    """Ставить автопостинг на паузу. Черга зберігається і продовжиться після запуску."""
    if config.status != AutoPostStatus.RUNNING:
        raise AutoPostError("Автопостинг не запущено")

    config.status = AutoPostStatus.PAUSED
    config.save(update_fields=["status"])


def build_post_payload(config: AutoPostConfig, pin, save_to_pin: bool = False) -> dict:
    """Готує дані для публікації піна (з AI-унікалізацією, якщо увімкнено)."""
    title = pin.title
    description = pin.description
    link = config.site_url

    uniqueness_config = config.uniqueness_config if config.use_uniqueness else None

    if uniqueness_config and uniqueness_config.is_active and title:
        unique_data = AutoPostUniquenessService(uniqueness_config).uniquify(
            title=title,
            description=description,
            alt_text=pin.alt_text,
            annotation=pin.annotation,
        )

        if unique_data:
            title = unique_data["title"]
            description = unique_data["description"]
        else:
            logger.warning(f"[AUTOPOST] Не вдалося унікалізувати пін #{pin.id}")

        if unique_data and save_to_pin:
            pin.utitle = title
            pin.udescription = description
            pin.slug_url = f"{config.site_url}{AutoPostUniquenessService.generate_slug(title)}"
            pin.save(update_fields=["utitle", "udescription", "slug_url"])

    if title:
        link = f"{config.site_url}{AutoPostUniquenessService.generate_slug(title)}"

    # Використовуємо оригінальне посилання Pinterest на фото,
    # бо Pinterest не приймає посилання без HTTPS та домену
    return {
        "title": title,
        "description": description,
        "link": link,
        "image_url": pin.image_url,
        "board_name": config.board_name,
    }


def publish(config: AutoPostConfig, payload: dict, timeout: int = 62) -> requests.Response:
    headers = {"Host": settings.AUTOPOST_API_HOST} if settings.AUTOPOST_API_HOST else None
    return requests.post(
        f"{settings.AUTOPOST_API_URL.rstrip('/')}/api/v1/publish/{config.webhook_token}/",
        json=payload,
        params={"wait": "true", "timeout": "60"},
        headers=headers,
        timeout=timeout,
    )


def reschedule_pending(config: AutoPostConfig) -> int:
    """Перераховує розклад pending-пінів від поточного часу з інтервалами конфігурації."""
    pending_items = list(
        AutoPostQueue.objects.filter(
            config=config,
            status=PostQueueStatus.PENDING,
        ).order_by("scheduled_at", "id")
    )

    prev_time = timezone.now()
    for idx, item in enumerate(pending_items):
        if idx == 0:
            item.scheduled_at = max(item.scheduled_at, prev_time)
        else:
            delay_minutes = random.randint(config.min_interval, config.max_interval)
            item.scheduled_at = prev_time + timedelta(minutes=delay_minutes)
        prev_time = item.scheduled_at

    AutoPostQueue.objects.bulk_update(pending_items, ["scheduled_at"], batch_size=500)
    return len(pending_items)
