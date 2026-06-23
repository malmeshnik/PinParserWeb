from celery import shared_task
from loguru import logger
from django.core.cache import cache
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
import random
import requests

from apps.tasks.models import ParseTask, TaskStatus, AutoPostConfig, AutoPostStatus, AutoPostQueue, PostQueueStatus
from apps.parser.services.pipeline import PinterestParsePipeline
from apps.results.tasks import export_results_to_excel
from apps.results.models import PinResult
from apps.uniqueness.tasks import run_uniqueness, generate_slugs
from apps.tasks.services.groq_uniqueness_service import GroqUniquenessService


@shared_task(bind=True, time_limit=10800)
def run_parse_task(self, task_id: int):

    lock_key = f"parse_task_lock_{task_id}"

    lock_acquired = cache.add(lock_key, self.request.id, timeout=10800)

    if not lock_acquired:
        logger.warning(f"Task {task_id} already running. Skipping duplicate.")
        return {"skipped": True}

    task = ParseTask.objects.get(id=task_id)

    try:
        task.mark_running(self.request.id)

        pipeline = PinterestParsePipeline(
            task=task,
            headless=True,
        )

        parsed_count = pipeline.run()

        task.refresh_from_db()

        if task.status == TaskStatus.STOPPED:
            return {"parsed": parsed_count}

        if task.use_uniqueness:
            task.mark_wait_uniqueness()
            (
                run_uniqueness.s(task.id, mark_done=False)
                | generate_slugs.si(task.id, mark_done=False)
                | export_results_to_excel.si(task.id)
            ).apply_async()
        else:
            export_results_to_excel.delay(task.id)

        return {"parsed": parsed_count}

    except Exception as e:
        logger.exception(f"Parse task {task_id} failed")
        task.mark_failed(str(e))
        raise

    finally:
        current_lock = cache.get(lock_key)

        if current_lock == self.request.id:
            cache.delete(lock_key)


@shared_task
def initialize_autopost_queue(autopost_config_id: int):
    """
    Ініціалізує чергу постів для автопостингу.
    Викликається один раз при запуску автопостингу.

    Args:
        autopost_config_id: ID конфігурації автопостингу
    """
    try:
        config = AutoPostConfig.objects.select_related('task').get(id=autopost_config_id)
    except AutoPostConfig.DoesNotExist:
        logger.error(f"[AUTOPOST] Конфігурацію {autopost_config_id} не знайдено")
        return

    logger.info(f"[AUTOPOST] Ініціалізація черги для завдання #{config.task.id}")

    # Отримуємо всі піни завдання
    pins = PinResult.objects.filter(task=config.task).order_by('id')
    config.total_count = pins.count()
    config.posted_count = 0
    config.status = AutoPostStatus.RUNNING
    config.started_at = timezone.now()
    config.error_message = None
    config.save(update_fields=['total_count', 'posted_count', 'status', 'started_at', 'error_message'])

    if config.total_count == 0:
        logger.warning(f"[AUTOPOST] Немає пінів для постингу в завданні #{config.task.id}")
        config.status = AutoPostStatus.COMPLETED
        config.finished_at = timezone.now()
        config.save(update_fields=['status', 'finished_at'])
        return

    # Створюємо черговий елемент для кожного піна
    queue_items = []
    current_time = timezone.now()

    for idx, pin in enumerate(pins):
        # Перший пін постимо зразу, решта з інтервалами
        if idx == 0:
            scheduled_at = current_time
        else:
            delay_minutes = random.randint(config.min_interval, config.max_interval)
            scheduled_at = current_time + timedelta(minutes=delay_minutes * idx)

        queue_items.append(
            AutoPostQueue(
                config=config,
                pin=pin,
                scheduled_at=scheduled_at,
                status=PostQueueStatus.PENDING,
            )
        )

    AutoPostQueue.objects.bulk_create(queue_items, batch_size=500)
    logger.success(
        f"[AUTOPOST] Створено {len(queue_items)} елементів черги для завдання #{config.task.id}"
    )


@shared_task
def process_autopost_queue():
    """
    Періодичний task (запускається кожні 1-5 хвилин через Celery Beat).
    Перевіряє чергу та постить готові піни.
    """
    now = timezone.now()

    # Знаходимо всі готові до постингу елементи черги
    ready_items = AutoPostQueue.objects.select_related(
        'config', 'config__task', 'pin'
    ).filter(
        status=PostQueueStatus.PENDING,
        scheduled_at__lte=now,
        config__status=AutoPostStatus.RUNNING,
    ).order_by('scheduled_at')[:50]  # Обмежуємо за раз щоб не перевантажити

    if not ready_items:
        return

    logger.info(f"[AUTOPOST QUEUE] Знайдено {len(ready_items)} готових постів")

    for item in ready_items:
        try:
            _process_single_post(item)
        except Exception as e:
            logger.error(f"[AUTOPOST QUEUE] Помилка обробки поста #{item.id}: {e}")
            item.status = PostQueueStatus.FAILED
            item.error_message = str(e)[:5000]
            item.attempts += 1
            item.save(update_fields=['status', 'error_message', 'attempts'])

    # Перевіряємо чи завершилось постинг для кожної конфігурації
    _check_completion()


def _process_single_post(item: AutoPostQueue):
    """Обробка одного поста з черги"""
    config = item.config
    pin = item.pin

    logger.info(f"[AUTOPOST] Обробка піна #{pin.id} для завдання #{config.task.id}")

    # Унікалізація якщо потрібно
    final_title = pin.title or ""
    final_description = pin.description or ""
    final_slug_url = ""

    if config.use_uniqueness and config.groq_api_key and final_title:
        groq_service = GroqUniquenessService(
            api_key=config.groq_api_key,
            prompt_template=config.groq_prompt or ""
        )

        logger.info(f"[AUTOPOST] Унікалізація піна #{pin.id}")
        unique_data = groq_service.uniquify(
            title=final_title,
            description=final_description,
            alt_text=pin.alt_text or "",
            annotation=pin.annotation or "",
        )

        if unique_data:
            final_title = unique_data["title"]
            final_description = unique_data["description"]

            pin.utitle = final_title
            pin.udescription = final_description

            slug_text = GroqUniquenessService.generate_slug(final_title)
            final_slug_url = f"{config.site_url}{slug_text}"
            pin.slug_url = final_slug_url

            pin.save(update_fields=['utitle', 'udescription', 'slug_url'])
        else:
            logger.warning(f"[AUTOPOST] Не вдалося унікалізувати пін #{pin.id}")
            slug_text = GroqUniquenessService.generate_slug(final_title)
            final_slug_url = f"{config.site_url}{slug_text}"
    else:
        if final_title:
            slug_text = GroqUniquenessService.generate_slug(final_title)
            final_slug_url = f"{config.site_url}{slug_text}"

    # Формуємо URL фото - використовуємо оригінальне Pinterest посилання
    # бо Pinterest не приймає посилання без HTTPS та домену
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

    response = requests.post(
        webhook_url,
        json=payload,
        timeout=30,
    )

    if response.status_code in [200, 201, 202]:
        # Успіх
        with transaction.atomic():
            item.status = PostQueueStatus.POSTED
            item.posted_at = timezone.now()
            item.attempts += 1
            item.save(update_fields=['status', 'posted_at', 'attempts'])

            config.posted_count += 1
            config.save(update_fields=['posted_count'])

        logger.success(
            f"[AUTOPOST] Опубліковано пін #{pin.id} | "
            f"Прогрес: {config.posted_count}/{config.total_count}"
        )
    else:
        # Помилка
        error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
        item.status = PostQueueStatus.FAILED
        item.error_message = error_msg
        item.attempts += 1
        item.save(update_fields=['status', 'error_message', 'attempts'])

        logger.error(
            f"[AUTOPOST] Помилка публікації піна #{pin.id} | {error_msg}"
        )


def _check_completion():
    """Перевіряє чи завершились активні конфігурації автопостингу"""
    active_configs = AutoPostConfig.objects.filter(
        status=AutoPostStatus.RUNNING
    )

    for config in active_configs:
        pending_count = config.queue_items.filter(
            status=PostQueueStatus.PENDING
        ).count()

        if pending_count == 0:
            config.status = AutoPostStatus.COMPLETED
            config.finished_at = timezone.now()
            config.save(update_fields=['status', 'finished_at'])
            logger.success(
                f"[AUTOPOST] Завершено для завдання #{config.task.id} | "
                f"Опубліковано: {config.posted_count}/{config.total_count}"
            )