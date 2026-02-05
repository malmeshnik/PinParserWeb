from django.db import models
from apps.proxies.models import Proxy


# Create your models here.
class AccountStatus(models.TextChoices):
    ACTIVE = "active", "Активний"
    BANNED = "banned", "Заблокований"
    ERROR = "error", "Помилка"


class PinterestAccount(models.Model):
    name = models.CharField(
        max_length=255,
        help_text="Вигадане імя для адмінів",
        verbose_name="Ім'я аккаунту",
    )

    cookies = models.JSONField(
        help_text="Pinterest cookies (експортовані з браузеру)",
        verbose_name="Cookies аккаунту",
    )

    proxy = models.ForeignKey(
        "proxies.Proxy",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="Проксі для аккаунту",
        related_name="accounts",
    )

    status = models.CharField(
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
        verbose_name="Статус аккаунту",
    )

    fail_count = models.PositiveSmallIntegerField(
        default=0, verbose_name="Кількість помилок"
    )

    last_used_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Останнє використання"
    )

    is_active = models.BooleanField(
        default=True, verbose_name="Активний для використання"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата створення")

    class Meta:
        verbose_name = "Pinterest аккаунт"
        verbose_name_plural = "Pinterest аккаунти"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Аккаунт №{self.id} - {self.name}"