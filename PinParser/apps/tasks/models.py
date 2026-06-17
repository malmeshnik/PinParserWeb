from django.db import models
from django.utils import timezone


# Create your models here.
class TaskStatus(models.TextChoices):
    PENDING = "pending", "Очікує"
    RUNNING = "running", "В процесі"
    WAITING_UNIQUENESS = 'waiting_uniqueness', "Очікує унікалізації",
    UNIQUENESS = "uniqueness", "Унікалізація"
    DONE = "done", "Виконано"
    ERROR = "error", "Помилка"
    STOPPED = "stopped", "Зупинено"


class AutoPostStatus(models.TextChoices):
    IDLE = "idle", "Не активний"
    RUNNING = "running", "Постинг"
    PAUSED = "paused", "На паузі"
    COMPLETED = "completed", "Завершено"
    ERROR = "error", "Помилка"


class PostQueueStatus(models.TextChoices):
    PENDING = "pending", "Очікує"
    POSTED = "posted", "Опубліковано"
    FAILED = "failed", "Помилка"
    SKIPPED = "skipped", "Пропущено"


from django.conf import settings

def get_default_uniqueness_config():
        from apps.uniqueness.models import UniquenessConfig

        config = (
            UniquenessConfig.objects
            .filter(is_active=True)
            .order_by("id")
            .first()
        )

        return config.id if config else None

class ParseTask(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Власник",
        null=True,
        blank=True
    )
    name = models.CharField(max_length=255, verbose_name="Назва завдання")
    keywords = models.JSONField(verbose_name="Ключові слова", default=list)

    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        verbose_name="Статус завдання",
    )

    threads = models.PositiveSmallIntegerField(
        default=3, verbose_name="Кількість потоків"
    )
    use_uniqueness = models.BooleanField(
        default=True, verbose_name="Використовувати унікальність"
    )
    uniqueness_config = models.ForeignKey(
        "uniqueness.UniquenessConfig",
        on_delete=models.SET_NULL,
        related_name="parse_task",
        null=True,
        blank=True,
        default=get_default_uniqueness_config,
        verbose_name="Конфіг унікалізації"
    )
    auto_sheet_name = models.BooleanField(
        default=True, verbose_name="Автоматична назва таблиці"
    )

    table_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Назва таблиці результатів",
    )

    export_file = models.FileField(
        upload_to="exports/",
        null=True,
        blank=True
    )

    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="ID Celery задачі",
        db_index=True,
    )

    total_urls = models.PositiveIntegerField(
        default=0,
        verbose_name="Зібрано Пінів",
    )

    processed_urls = models.PositiveIntegerField(
        default=0,
        verbose_name="Оброблено Пінів",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата створення")
    started_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Дата початку"
    )
    finished_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Дата завершення"
    )

    error_message = models.TextField(
        blank=True, null=True, verbose_name="Повідомлення про помилку"
    )

    class Meta:
        verbose_name = "Завдання парсингу"
        verbose_name_plural = "Завдання парсингу"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["owner", "-created_at"]),
        ]

    def __str__(self):
        return f"Завдання №{self.id} - {self.name}"
    
    def mark_running(self, celery_task_id: str):
        self.status = TaskStatus.RUNNING
        self.celery_task_id = celery_task_id
        self.processed_urls = 0
        self.total_urls = 0
        self.error_message = ''
        self.started_at = timezone.now()
        self.save(update_fields=[
            "status", "celery_task_id", "started_at", "error_message", "total_urls"
        ])

    def mark_success(self):
        self.status = TaskStatus.DONE
        self.finished_at = timezone.now()
        self.celery_task_id = None
        self.save(update_fields=[
            "status", "total_urls", "finished_at", "celery_task_id"
        ])

    def mark_failed(self, error: str):
        self.status = TaskStatus.ERROR
        self.error_message = error[:5000]
        self.finished_at = timezone.now()
        self.celery_task_id = None
        self.save(update_fields=[
            "status", "error_message", "finished_at", "celery_task_id"
        ])

    def update_progress(self, processed: int, total: int | None = None):
        self.processed_urls = processed
        if total is not None:
            self.total_urls = total
        self.save(update_fields=[
            "processed_urls", "total_urls"
        ])

    def mark_wait_uniqueness(self):
        self.status = TaskStatus.WAITING_UNIQUENESS
        self.save(update_fields=['status'])


class AutoPostConfig(models.Model):
    task = models.OneToOneField(
        ParseTask,
        on_delete=models.CASCADE,
        related_name="autopost_config",
        verbose_name="Завдання",
    )

    webhook_token = models.UUIDField(
        verbose_name="Webhook токен",
        help_text="UUID токен з сервісу автопостингу",
        blank=True,
        null=True,
    )

    board_name = models.CharField(
        max_length=255,
        verbose_name="Назва дошки Pinterest",
    )

    min_interval = models.PositiveIntegerField(
        default=100,
        verbose_name="Мінімальний інтервал (хвилини)",
        help_text="Мінімальний час між постами в хвилинах",
    )

    max_interval = models.PositiveIntegerField(
        default=200,
        verbose_name="Максимальний інтервал (хвилини)",
        help_text="Максимальний час між постами в хвилинах",
    )

    site_url = models.URLField(
        max_length=500,
        verbose_name="Базовий URL сайту",
        help_text="Наприклад: https://example.com/?",
        default="https://example.com/?",
    )

    use_uniqueness = models.BooleanField(
        default=True,
        verbose_name="Унікалізувати перед постингом",
    )

    groq_api_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Groq API ключ",
        help_text="Ключ для унікалізації через Groq",
    )

    groq_prompt = models.TextField(
        blank=True,
        null=True,
        verbose_name="Промпт для унікалізації",
        help_text="Кастомний промпт для Groq API",
        default=(
            "Uniquify the following Pinterest pin content. Return ONLY a JSON object with 'title' and 'description' keys.\n\n"
            "Original Title: {{title}}\n"
            "Original Description: {{description}}\n"
            "Alt Text: {{alt_text}}\n"
            "Annotation: {{annotation}}\n\n"
            "CRITICAL RULES:\n"
            "1. Rewrite title and description to make them 100% unique, engaging, and clicking.\n"
            "2. Keep the EXACT SAME LANGUAGE as the input text (e.g. if input is Ukrainian, output Ukrainian).\n"
            "3. Return ONLY valid JSON, do not include markdown blocks like ```json, no explanations."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=AutoPostStatus.choices,
        default=AutoPostStatus.IDLE,
        verbose_name="Статус автопостингу",
    )

    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="ID Celery задачі автопостингу",
    )

    posted_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Опубліковано пінів",
    )

    total_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Всього пінів",
    )

    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name="Повідомлення про помилку",
    )

    started_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Дата початку постингу",
    )

    finished_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Дата завершення постингу",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата створення",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата оновлення",
    )

    class Meta:
        verbose_name = "Налаштування автопостингу"
        verbose_name_plural = "Налаштування автопостингу"

    def __str__(self):
        return f"Автопостинг для завдання #{self.task.id}"


class AutoPostQueue(models.Model):
    """Черга для автопостингу пінів"""

    config = models.ForeignKey(
        AutoPostConfig,
        on_delete=models.CASCADE,
        related_name="queue_items",
        verbose_name="Конфігурація автопостингу",
    )

    pin = models.ForeignKey(
        "results.PinResult",
        on_delete=models.CASCADE,
        related_name="post_queue_items",
        verbose_name="Пін",
    )

    scheduled_at = models.DateTimeField(
        verbose_name="Заплановано на",
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=PostQueueStatus.choices,
        default=PostQueueStatus.PENDING,
        verbose_name="Статус",
        db_index=True,
    )

    posted_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Опубліковано",
    )

    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name="Повідомлення про помилку",
    )

    attempts = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Кількість спроб",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата створення",
    )

    class Meta:
        verbose_name = "Елемент черги автопостингу"
        verbose_name_plural = "Черга автопостингу"
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["config", "status"]),
        ]

    def __str__(self):
        return f"Пост #{self.pin.id} заплановано на {self.scheduled_at}"