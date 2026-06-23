from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from loguru import logger


# Create your models here.
class ProxyStatus(models.TextChoices):
    ACTIVE = "active", _("Активный")
    DEAD = "dead", _("Мертвый")
    ERROR = "error", _("Ошибка")


class Proxy(models.Model):
    name = models.CharField(
        max_length=255,
        help_text=_("Вымышленное имя для админов"),
        verbose_name=_("Имя прокси"),
    )

    is_9proxy = models.BooleanField(
        default=False,
        verbose_name=_("Это динамическое 9Proxy"),
        help_text=_("Если включено, хост и порт будут получены автоматически через 9Proxy API")
    )

    host = models.CharField(
        max_length=255,
        verbose_name=_("Хост прокси"),
        blank=True,
        null=True,
    )
    port = models.PositiveIntegerField(
        verbose_name=_("Порт прокси"),
        blank=True,
        null=True,
    )

    username = models.CharField(
        max_length=255,
        verbose_name=_("Пользователь прокси"),
        blank=True,
        null=True,
        help_text=_("Если прокси требует аутентификации, укажите имя пользователя")
    )

    password = models.CharField(
        max_length=255,
        verbose_name=_("Пароль прокси"),
        blank=True,
        null=True,
        help_text=_("Если прокси требует аутентификации, укажите пароль")
    )

    country = models.CharField(
        max_length=50, verbose_name=_("Страна прокси"), blank=True, null=True
    )
    state = models.CharField(
        max_length=50, verbose_name=_("Штат/Область прокси"), blank=True, null=True
    )
    city = models.CharField(
        max_length=50, verbose_name=_("Город прокси"), blank=True, null=True
    )
    zip = models.CharField(
        max_length=20, verbose_name=_("Почтовый индекс прокси"), blank=True, null=True
    )
    isp = models.CharField(
        max_length=100, verbose_name=_("ISP прокси"), blank=True, null=True
    )

    status = models.CharField(
        max_length=20,
        choices=ProxyStatus.choices,
        default=ProxyStatus.ACTIVE,
        verbose_name=_("Статус прокси"),
    )

    fail_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Количество ошибок")
    )
    last_checked_at = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Последняя проверка")
    )
    is_active = models.BooleanField(
        default=True, verbose_name=_("Активен для использования")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))

    class Meta:
        verbose_name = _("Прокси")
        verbose_name_plural = _("Прокси")
        ordering = ["-created_at"]

    def __str__(self):
        return _("Прокси №%(id)s - %(name)s") % {"id": self.id, "name": self.name}

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
