from celery import shared_task, chain
from loguru import logger
from django.core.cache import cache
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
import random

from apps.tasks.models import ParseTask, TaskStatus, AutoPostConfig, AutoPostStatus, AutoPostQueue, PostQueueStatus
from apps.parser.services.pipeline import PinterestParsePipeline
from apps.results.tasks import export_results_to_excel
from apps.results.models import PinResult
from apps.uniqueness.tasks import run_uniqueness, generate_slugs
from apps.tasks.services.task_control import parse_lock_key
from apps.tasks.services.autopost_service import build_post_payload, publish, reschedule_pending


@shared_task(bind=True, time_limit=10800)
def run_parse_task(self, task_id: int):

    lock_key = parse_lock_key(task_id)

    lock_acquired = cache.add(lock_key, self.request.id, timeout=10800)

    if not lock_acquired:
        logger.warning(f"Task {task_id} already running. Skipping duplicate.")
        return {"skipped": True}

    try:
        task = ParseTask.objects.get(id=task_id)

        if task.status == TaskStatus.STOPPED:
            return {"skipped": True}

        try:
            task.mark_running(self.request.id)

            parsed_count = PinterestParsePipeline(task=task, headless=True).run()

            task.refresh_from_db()

            if task.status == TaskStatus.STOPPED:
                return {"parsed": parsed_count}

            if task.use_uniqueness:
                task.mark_wait_uniqueness()
                chain(
                    run_uniqueness.si(task.id, chained=True),
                    generate_slugs.si(task.id, chained=True),
                    export_results_to_excel.si(task.id, chained=True),
                ).apply_async()
            else:
                export_results_to_excel.delay(task.id, chained=True)

            return {"parsed": parsed_count}

        except Exception as e:
            logger.exception(f"Parse task {task_id} failed")
            task.refresh_from_db(fields=["status"])
            if task.status != TaskStatus.STOPPED:
                task.mark_failed(str(e))
            raise

    finally:
        if cache.get(lock_key) == self.request.id:
            cache.delete(lock_key)


@shared_task
def initialize_autopost_queue(autopost_config_id: int):
    """
    Запускає автопостинг: створює чергу постів або відновлює її після паузи.

    Args:
        autopost_config_id: ID конфігурації автопостингу
    """
    try:
        config = AutoPostConfig.objects.select_related('task').get(id=autopost_config_id)
    except AutoPostConfig.DoesNotExist:
        logger.error(f"[AUTOPOST] Конфігурацію {autopost_config_id} не знайдено")
        return

    # Відновлення після паузи: продовжуємо існуючу чергу, а не створюємо дублікати
    if config.queue_items.filter(status=PostQueueStatus.PENDING).exists():
        count = reschedule_pending(config)
        config.status = AutoPostStatus.RUNNING
        config.error_message = None
        config.finished_at = None
        config.save(update_fields=['status', 'error_message', 'finished_at'])
        logger.info(f"[AUTOPOST] Відновлено чергу ({count} пінів) для завдання #{config.task.id}")
        return

    logger.info(f"[AUTOPOST] Ініціалізація черги для завдання #{config.task.id}")

    # Вже опубліковані піни повторно не постимо, а невдалі ставимо в чергу заново
    config.queue_items.exclude(status=PostQueueStatus.POSTED).delete()
    posted_pin_ids = config.queue_items.filter(
        status=PostQueueStatus.POSTED
    ).values_list('pin_id', flat=True)
    all_pins = PinResult.objects.filter(task=config.task)
    pins = all_pins.exclude(id__in=posted_pin_ids).order_by('id')

    config.total_count = all_pins.count()
    config.posted_count = config.total_count - pins.count()
    config.status = AutoPostStatus.RUNNING
    config.started_at = timezone.now()
    config.finished_at = None
    config.error_message = None
    config.save(update_fields=['total_count', 'posted_count', 'status', 'started_at', 'finished_at', 'error_message'])

    # Перший пін постимо одразу, кожен наступний — через випадковий інтервал після попереднього
    queue_items = []
    scheduled_at = timezone.now()

    for idx, pin in enumerate(pins):
        if idx > 0:
            scheduled_at += timedelta(minutes=random.randint(config.min_interval, config.max_interval))

        queue_items.append(
            AutoPostQueue(
                config=config,
                pin=pin,
                scheduled_at=scheduled_at,
                status=PostQueueStatus.PENDING,
            )
        )

    if not queue_items:
        logger.warning(f"[AUTOPOST] Немає пінів для постингу в завданні #{config.task.id}")
        config.status = AutoPostStatus.COMPLETED
        config.finished_at = timezone.now()
        config.save(update_fields=['status', 'finished_at'])
        return

    AutoPostQueue.objects.bulk_create(queue_items, batch_size=500)
    logger.success(
        f"[AUTOPOST] Створено {len(queue_items)} елементів черги для завдання #{config.task.id}"
    )


AUTOPOST_QUEUE_LOCK = "autopost_queue_lock"


@shared_task
def process_autopost_queue():
    """
    Періодичний task (запускається через Celery Beat).
    Перевіряє чергу та постить готові піни.
    """
    # Один пост може тривати до хвилини, тож обробка може не встигнути до наступного
    # запуску beat — без лока два запуски взяли б ті самі піни і запостили їх двічі
    if not cache.add(AUTOPOST_QUEUE_LOCK, True, timeout=3600):
        logger.info("[AUTOPOST QUEUE] Попередня обробка ще триває, пропускаємо")
        return

    try:
        ready_items = list(AutoPostQueue.objects.select_related(
            'config', 'config__task', 'config__uniqueness_config', 'pin'
        ).filter(
            status=PostQueueStatus.PENDING,
            scheduled_at__lte=timezone.now(),
            config__status=AutoPostStatus.RUNNING,
        ).order_by('scheduled_at')[:50])  # Обмежуємо за раз щоб не перевантажити

        if ready_items:
            logger.info(f"[AUTOPOST QUEUE] Знайдено {len(ready_items)} готових постів")

        for item in ready_items:
            try:
                _process_single_post(item)
            except Exception as e:
                logger.bind(autopost_config_id=item.config_id, pin_id=item.pin_id, task_id=item.config.task_id).exception(
                    f"[AUTOPOST QUEUE] Помилка обробки поста #{item.id}: {e}"
                )
                _mark_post_failed(item, str(e))

        _check_completion()
    finally:
        cache.delete(AUTOPOST_QUEUE_LOCK)


def _process_single_post(item: AutoPostQueue):
    """Обробка одного поста з черги"""
    config = item.config
    pin = item.pin

    logger.info(f"[AUTOPOST] Обробка піна #{pin.id} для завдання #{config.task.id}")

    payload = build_post_payload(config, pin, save_to_pin=True)
    response = publish(config, payload)

    if response.status_code in (200, 201, 202):
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
        error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
        _mark_post_failed(item, error_msg)
        logger.bind(autopost_config_id=config.id, pin_id=pin.id, task_id=config.task_id).error(
            f"[AUTOPOST] Помилка публікації піна #{pin.id} | {error_msg}"
        )


def _mark_post_failed(item: AutoPostQueue, error: str):
    item.status = PostQueueStatus.FAILED
    item.error_message = error[:5000]
    item.attempts += 1
    item.save(update_fields=['status', 'error_message', 'attempts'])


def _check_completion():
    """Перевіряє чи завершились активні конфігурації автопостингу"""
    active_configs = AutoPostConfig.objects.filter(
        status=AutoPostStatus.RUNNING
    ).select_related('task')

    for config in active_configs:
        if config.queue_items.filter(status=PostQueueStatus.PENDING).exists():
            continue

        failed_count = config.queue_items.filter(status=PostQueueStatus.FAILED).count()

        if failed_count and config.posted_count == 0:
            config.status = AutoPostStatus.ERROR
            config.error_message = f"Не вдалося опублікувати жодного піна ({failed_count} помилок)"
        else:
            config.status = AutoPostStatus.COMPLETED
            if failed_count:
                config.error_message = f"Не опубліковано {failed_count} пінів, деталі в черзі автопостингу"

        config.finished_at = timezone.now()
        config.save(update_fields=['status', 'error_message', 'finished_at'])

        if config.error_message:
            log = logger.bind(db=True, source="autopost", autopost_config_id=config.id, task_id=config.task_id)
            if config.status == AutoPostStatus.ERROR:
                log.error(f"[AUTOPOST] Завдання #{config.task_id}: {config.error_message}")
            else:
                log.warning(f"[AUTOPOST] Завдання #{config.task_id}: {config.error_message}")

        logger.info(
            f"[AUTOPOST] Завершено для завдання #{config.task.id} | "
            f"Опубліковано: {config.posted_count}/{config.total_count} | Помилок: {failed_count}"
        )
