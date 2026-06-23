"""
Сервіс для тестування автопостингу.
Синхронно відправляє перший пін для перевірки налаштувань.
"""
import requests
from loguru import logger
from django.db import transaction
from django.utils import timezone

from apps.tasks.models import AutoPostConfig, AutoPostQueue, PostQueueStatus
from apps.results.models import PinResult
from apps.tasks.services.groq_uniqueness_service import GroqUniquenessService


def test_autopost_config(config: AutoPostConfig) -> dict:
    """
    Тестує конфігурацію автопостингу, відправляючи перший невідправлений пін.

    Args:
        config: Конфігурація автопостингу

    Returns:
        dict: Результат тесту з ключами:
            - success (bool): чи успішно відправлено
            - pin_id (int): ID піна
            - response_status (int): HTTP статус відповіді (якщо успішно)
            - error (str): текст помилки (якщо не успішно)
    """
    logger.info(f"[AUTOPOST TEST] Тестовий пост для завдання #{config.task.id}")

    # Знаходимо перший пін який ще не був відправлений
    # Спочатку шукаємо в черзі (якщо черга існує)
    pending_queue_item = AutoPostQueue.objects.filter(
        config=config,
        status=PostQueueStatus.PENDING
    ).order_by('scheduled_at').first()

    if pending_queue_item:
        pin = pending_queue_item.pin
        logger.info(f"[AUTOPOST TEST] Використовуємо пін #{pin.id} з черги")
    else:
        # Якщо черги немає, беремо перший пін з результатів
        pin = PinResult.objects.filter(task=config.task).order_by('id').first()

        if not pin:
            logger.warning(f"[AUTOPOST TEST] Немає пінів для тесту в завданні #{config.task.id}")
            return {
                "success": False,
                "pin_id": None,
                "error": "Немає пінів для тесту"
            }

        logger.info(f"[AUTOPOST TEST] Використовуємо пін #{pin.id} з результатів")

    # Обробляємо пін
    final_title = pin.title or ""
    final_description = pin.description or ""
    final_slug_url = ""

    if config.use_uniqueness and config.groq_api_key and final_title:
        groq_service = GroqUniquenessService(
            api_key=config.groq_api_key,
            prompt_template=config.groq_prompt or ""
        )

        logger.info(f"[AUTOPOST TEST] Унікалізація піна #{pin.id}")
        unique_data = groq_service.uniquify(
            title=final_title,
            description=final_description,
            alt_text=pin.alt_text or "",
            annotation=pin.annotation or "",
        )

        if unique_data:
            final_title = unique_data["title"]
            final_description = unique_data["description"]

            slug_text = GroqUniquenessService.generate_slug(final_title)
            final_slug_url = f"{config.site_url}{slug_text}"
        else:
            logger.warning(f"[AUTOPOST TEST] Не вдалося унікалізувати пін #{pin.id}")
            slug_text = GroqUniquenessService.generate_slug(final_title)
            final_slug_url = f"{config.site_url}{slug_text}"
    else:
        if final_title:
            slug_text = GroqUniquenessService.generate_slug(final_title)
            final_slug_url = f"{config.site_url}{slug_text}"

    image_url = pin.image_url or ""

    # Відправляємо на webhook
    payload = {
        "title": final_title,
        "description": final_description,
        "link": final_slug_url,
        "image_url": image_url,
        "board_name": config.board_name,
    }

    webhook_url = f"http://localhost:80/api/v1/publish/{config.webhook_token}/"

    try:
        # Додаємо параметр wait=true для синхронної відповіді
        response = requests.post(
            webhook_url,
            json=payload,
            params={'wait': 'true', 'timeout': '60'},
            timeout=65,  # Трохи більше ніж timeout на сервері
        )

        response_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}

        if response.status_code == 200:
            if pending_queue_item:
                with transaction.atomic():
                    pending_queue_item.status = PostQueueStatus.POSTED
                    pending_queue_item.posted_at = timezone.now()
                    pending_queue_item.attempts += 1
                    pending_queue_item.error_message = None
                    pending_queue_item.save(
                        update_fields=['status', 'posted_at', 'attempts', 'error_message']
                    )

                    config.posted_count += 1
                    config.save(update_fields=['posted_count'])

            # Пін успішно опубліковано
            logger.success(f"[AUTOPOST TEST] Тестовий пін #{pin.id} успішно опубліковано")
            return {
                "success": True,
                "pin_id": pin.id,
                "title": final_title,
                "response_status": response.status_code,
                "message": "Пін успішно опубліковано на Pinterest"
            }
        elif response.status_code == 202:
            # Task прийнято але ще обробляється (timeout)
            task_id = response_data.get('task_id', '')
            logger.warning(f"[AUTOPOST TEST] Пін #{pin.id} все ще обробляється. Task ID: {task_id}")
            return {
                "success": False,
                "pin_id": pin.id,
                "error": f"Таймаут: пін все ще обробляється (Task ID: {task_id}). Перевірте статус пізніше."
            }
        else:
            # Помилка публікації
            error_message = response_data.get('message', response.text[:500])
            error_type = response_data.get('error', 'unknown_error')

            logger.error(f"[AUTOPOST TEST] Помилка відправки піна #{pin.id} | HTTP {response.status_code}: {error_type}")
            return {
                "success": False,
                "pin_id": pin.id,
                "error": f"Помилка публікації ({error_type}): {error_message}"
            }
    except requests.exceptions.RequestException as e:
        error_msg = f"Помилка з'єднання: {str(e)}"
        logger.error(f"[AUTOPOST TEST] Exception при відправці піна #{pin.id}: {error_msg}")
        return {
            "success": False,
            "pin_id": pin.id,
            "error": error_msg
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[AUTOPOST TEST] Unexpected exception при відправці піна #{pin.id}: {error_msg}")
        return {
            "success": False,
            "pin_id": pin.id,
            "error": error_msg
        }
