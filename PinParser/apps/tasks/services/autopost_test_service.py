"""
Сервіс для тестування автопостингу.
Синхронно відправляє перший пін для перевірки налаштувань.
"""
import requests
from loguru import logger

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
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=30,
        )

        if response.status_code in (200, 201, 202):
            logger.success(f"[AUTOPOST TEST] Тестовий пін #{pin.id} успішно відправлено")
            return {
                "success": True,
                "pin_id": pin.id,
                "title": final_title,
                "response_status": response.status_code
            }
        else:
            error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
            logger.error(f"[AUTOPOST TEST] Помилка відправки піна #{pin.id} | {error_msg}")
            return {
                "success": False,
                "pin_id": pin.id,
                "error": error_msg
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
