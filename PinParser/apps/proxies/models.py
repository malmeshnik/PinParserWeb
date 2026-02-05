from django.db import models


# Create your models here.
class ProxyStatus(models.TextChoices):
    ACTIVE = "active", "Активний"
    DEAD = "dead", "Мертвий"
    ERROR = "error", "Помилка"


class Proxy(models.Model):
    name = models.CharField(
        max_length=255,
        help_text="Вигадане імя для адмінів",
        verbose_name="Ім'я проксі",
    )

    host = models.CharField(
        max_length=255,
        verbose_name="Хост проксі",
    )
    port = models.PositiveIntegerField(
        verbose_name="Порт проксі",
    )

    country = models.CharField(
        max_length=50, verbose_name="Країна проксі", blank=True, null=True
    )
    state = models.CharField(
        max_length=50, verbose_name="Штат/Область проксі", blank=True, null=True
    )
    city = models.CharField(
        max_length=50, verbose_name="Місто проксі", blank=True, null=True
    )
    zip = models.CharField(
        max_length=20, verbose_name="Поштовий індекс проксі", blank=True, null=True
    )
    isp = models.CharField(
        max_length=100, verbose_name="ISP проксі", blank=True, null=True
    )

    status = models.CharField(
        max_length=20,
        choices=ProxyStatus.choices,
        default=ProxyStatus.ACTIVE,
        verbose_name="Статус проксі",
    )

    fail_count = models.PositiveSmallIntegerField(
        default=0, verbose_name="Кількість помилок"
    )
    last_checked_at = models.DateTimeField(
        blank=True, null=True, verbose_name="Остання перевірка"
    )
    is_active = models.BooleanField(
        default=True, verbose_name="Активний для використання"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата створення")

    class Meta:
        verbose_name = "Проксі"
        verbose_name_plural = "Проксі"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Проксі №{self.id} - {self.name}"