from django.db import models
from django.utils.translation import gettext_lazy as _


class LogSource(models.TextChoices):
    PARSER = "parser", _("Парсинг")
    UNIQUENESS = "uniqueness", _("Уникализация")
    AUTOPOST = "autopost", _("Автопостинг")
    EXPORT = "export", _("Экспорт")
    CELERY = "celery", _("Celery")
    WEB = "web", _("Веб / админка")
    SYSTEM = "system", _("Система")


class LogLevel(models.TextChoices):
    WARNING = "WARNING", _("Предупреждение")
    ERROR = "ERROR", _("Ошибка")
    CRITICAL = "CRITICAL", _("Критическая")


class ErrorLog(models.Model):
    task = models.ForeignKey(
        'tasks.ParseTask',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logs',
        verbose_name=_("Задание")
    )
    account = models.ForeignKey(
        'accounts.PinterestAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Аккаунт")
    )
    source = models.CharField(
        max_length=20,
        choices=LogSource.choices,
        default=LogSource.SYSTEM,
        verbose_name=_("Источник"),
    )
    level = models.CharField(
        max_length=20,
        choices=LogLevel.choices,
        default=LogLevel.ERROR,
        verbose_name=_("Уровень"),
    )
    message = models.TextField(verbose_name=_("Сообщение"))
    traceback = models.TextField(blank=True, default="", verbose_name=_("Traceback"))
    logger_name = models.CharField(
        max_length=255, blank=True, default="",
        verbose_name=_("Место в коде"),
        help_text=_("Модуль:функция:строка"),
    )
    context = models.JSONField(
        default=dict, blank=True,
        verbose_name=_("Контекст"),
        help_text=_("Celery-задача, воркер, пин, запрос и т.д."),
    )
    fingerprint = models.CharField(
        max_length=40, blank=True, default="", db_index=True,
        verbose_name=_("Отпечаток"),
        help_text=_("Одинаковый у повторяющихся ошибок"),
    )
    is_resolved = models.BooleanField(default=False, verbose_name=_("Решено"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))

    class Meta:
        verbose_name = _("Лог ошибок")
        verbose_name_plural = _("Логи ошибок")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["source", "-created_at"]),
            models.Index(fields=["level", "-created_at"]),
            models.Index(fields=["is_resolved", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at} - {self.level} - {self.message[:50]}"
