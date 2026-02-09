from django.db import models
from django.utils import timezone


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

    def check_health(self):
        import requests
        proxy_url = f"http://{self.host}:{self.port}"
        try:
            resp = requests.get(
                "https://www.google.com",
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=10
            )
            if resp.status_code == 200:
                self.status = ProxyStatus.ACTIVE
                self.fail_count = 0
            else:
                self.fail_count += 1
        except Exception:
            self.fail_count += 1

        if self.fail_count >= 3:
            self.status = ProxyStatus.DEAD

        self.last_checked_at = timezone.now()
        self.save(update_fields=['status', 'fail_count', 'last_checked_at'])
        return self.status == ProxyStatus.ACTIVE


class NineProxyConfig(models.Model):
    country = models.CharField(
        max_length=50, verbose_name="Країна (код, напр. US, VN)", blank=True, null=True
    )
    state = models.CharField(
        max_length=50, verbose_name="Штат/Область", blank=True, null=True
    )
    city = models.CharField(
        max_length=50, verbose_name="Місто", blank=True, null=True
    )
    zip = models.CharField(
        max_length=20, verbose_name="Поштовий індекс", blank=True, null=True
    )
    isp = models.CharField(
        max_length=100, verbose_name="ISP", blank=True, null=True
    )

    updated_at = models.DateTimeField(auto_now=True, verbose_name="Останнє оновлення")

    class Meta:
        verbose_name = "Налаштування 9Proxy"
        verbose_name_plural = "Налаштування 9Proxy"

    def __str__(self):
        return f"Налаштування 9Proxy від {self.updated_at.strftime('%Y-%m-%d %H:%M')}"