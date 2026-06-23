from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings


# Create your models here.
class TaskStatus(models.TextChoices):
    PENDING = "pending", _("Ожидает")
    RUNNING = "running", _("В процессе")
    WAITING_UNIQUENESS = 'waiting_uniqueness', _("Ожидает уникализации"),
    UNIQUENESS = "uniqueness", _("Уникализация")
    DONE = "done", _("Выполнено")
    ERROR = "error", _("Ошибка")
    STOPPED = "stopped", _("Остановлено")


class AutoPostStatus(models.TextChoices):
    IDLE = "idle", _("Не активен")
    RUNNING = "running", _("Постинг")
    PAUSED = "paused", _("На паузе")
    COMPLETED = "completed", _("Завершено")
    ERROR = "error", _("Ошибка")


class PostQueueStatus(models.TextChoices):
    PENDING = "pending", _("Ожидает")
    POSTED = "posted", _("Опубликовано")
    FAILED = "failed", _("Ошибка")
    SKIPPED = "skipped", _("Пропущено")


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
        verbose_name=_("Владелец"),
        null=True,
        blank=True
    )
    name = models.CharField(max_length=255, verbose_name=_("Название задания"))
    keywords = models.JSONField(verbose_name=_("Ключевые слова"), default=list)

    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        verbose_name=_("Статус задания"),
    )

    threads = models.PositiveSmallIntegerField(
        default=3, verbose_name=_("Количество потоков")
    )
    use_uniqueness = models.BooleanField(
        default=True, verbose_name=_("Использовать уникальность")
    )
    uniqueness_config = models.ForeignKey(
        "uniqueness.UniquenessConfig",
        on_delete=models.SET_NULL,
        related_name="parse_task",
        null=True,
        blank=True,
        default=get_default_uniqueness_config,
        verbose_name=_("Конфиг уникализации")
    )
    auto_sheet_name = models.BooleanField(
        default=True, verbose_name=_("Автоматическое название таблицы")
    )

    table_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Название таблицы результатов"),
    )

    export_file = models.FileField(
        upload_to="exports/",
        null=True,
        blank=True,
        verbose_name=_("Файл экспорта")
    )

    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("ID Celery задачи"),
        db_index=True,
    )

    total_urls = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Найдено Пинов"),
    )

    processed_urls = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Собрано Пинов"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))
    started_at = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Дата начала")
    )
    finished_at = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Дата завершения")
    )

    error_message = models.TextField(
        blank=True, null=True, verbose_name=_("Сообщение об ошибке")
    )

    class Meta:
        verbose_name = _("Задание парсинга")
        verbose_name_plural = _("Задания парсинга")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["owner", "-created_at"]),
        ]

    def __str__(self):
        return _("Задание №%(id)s - %(name)s") % {"id": self.id, "name": self.name}
    
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
        verbose_name=_("Задание"),
    )

    webhook_token = models.UUIDField(
        verbose_name=_("Webhook токен"),
        help_text=_("UUID токен из сервиса автопостинга"),
        blank=True,
        null=True,
    )

    board_name = models.CharField(
        max_length=255,
        verbose_name=_("Название доски Pinterest"),
    )

    min_interval = models.PositiveIntegerField(
        default=100,
        verbose_name=_("Минимальный интервал (минуты)"),
        help_text=_("Минимальное время между постами в минутах"),
    )

    max_interval = models.PositiveIntegerField(
        default=200,
        verbose_name=_("Максимальный интервал (минуты)"),
        help_text=_("Максимальное время между постами в минутах"),
    )

    site_url = models.URLField(
        max_length=500,
        verbose_name=_("Базовый URL сайта"),
        help_text=_("Например: https://example.com/?"),
        default="https://example.com/?",
    )

    use_uniqueness = models.BooleanField(
        default=True,
        verbose_name=_("Уникализировать перед постингом"),
    )

    groq_api_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Groq API ключ"),
        help_text=_("Ключ для уникализации через Groq"),
    )

    groq_prompt = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Промпт для уникализации"),
        help_text=_("Кастомный промпт для Groq API"),
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
        verbose_name=_("Статус автопостинга"),
    )

    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("ID Celery задачи автопостинга"),
    )

    posted_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Опубликовано пинов"),
    )

    total_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Всего пинов"),
    )

    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Сообщение об ошибке"),
    )

    started_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Дата начала постинга"),
    )

    finished_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Дата завершения постинга"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Дата обновления"),
    )

    class Meta:
        verbose_name = _("Настройка автопостинга")
        verbose_name_plural = _("Настройки автопостинга")

    def __str__(self):
        return _("Автопостинг для задания #%(id)s") % {"id": self.task.id}


class AutoPostQueue(models.Model):
    """Черга для автопостингу пінів"""

    config = models.ForeignKey(
        AutoPostConfig,
        on_delete=models.CASCADE,
        related_name="queue_items",
        verbose_name=_("Конфигурация автопостинга"),
    )

    pin = models.ForeignKey(
        "results.PinResult",
        on_delete=models.CASCADE,
        related_name="post_queue_items",
        verbose_name=_("Пин"),
    )

    scheduled_at = models.DateTimeField(
        verbose_name=_("Запланировано на"),
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=PostQueueStatus.choices,
        default=PostQueueStatus.PENDING,
        verbose_name=_("Статус"),
        db_index=True,
    )

    posted_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Опубликовано"),
    )

    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Сообщение об ошибке"),
    )

    attempts = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Количество попыток"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата создания"),
    )

    class Meta:
        verbose_name = _("Элемент очереди автопостинга")
        verbose_name_plural = _("Очередь автопостинга")
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["config", "status"]),
        ]

    def __str__(self):
        return _("Пост #%(pin_id)s запланирован на %(time)s") % {
            "pin_id": self.pin.id,
            "time": self.scheduled_at
        }
