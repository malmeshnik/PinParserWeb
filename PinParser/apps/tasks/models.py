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
        self.save(update_fields=[
            "status", "total_urls", "finished_at"
        ])

    def mark_failed(self, error: str):
        self.status = TaskStatus.ERROR
        self.error_message = error[:5000]
        self.finished_at = timezone.now()
        self.save(update_fields=[
            "status", "error_message", "finished_at"
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