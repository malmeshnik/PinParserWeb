from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.proxies.models import Proxy


# Create your models here.
class AccountStatus(models.TextChoices):
    ACTIVE = "active", _("Активный")
    BANNED = "banned", _("Заблокирован")
    ERROR = "error", _("Ошибка")


class PinterestAccount(models.Model):
    name = models.CharField(
        max_length=255,
        help_text=_("Вымышленное имя для админов"),
        verbose_name=_("Имя аккаунта"),
    )

    cookies = models.JSONField(
        help_text=_("Pinterest cookies (экспортированные из браузера)"),
        verbose_name=_("Cookies аккаунта"),
    )

    proxy = models.ForeignKey(
        "proxies.Proxy",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Прокси для аккаунта"),
        related_name="accounts",
    )

    status = models.CharField(
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
        verbose_name=_("Статус аккаунта"),
    )

    fail_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Количество ошибок")
    )

    last_used_at = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Последнее использование")
    )

    user_agent = models.TextField(
        blank=True, null=True, verbose_name=_("User-Agent")
    )

    is_active = models.BooleanField(
        default=True, verbose_name=_("Активен для использования")
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))

    class Meta:
        verbose_name = _("Pinterest аккаунт")
        verbose_name_plural = _("Pinterest аккаунты")
        ordering = ["-created_at"]

    def __str__(self):
        return _("Аккаунт №%(id)s - %(name)s") % {"id": self.id, "name": self.name}

    def register_fail(self):
        self.fail_count += 1
        if self.fail_count >= 3:
            self.status = AccountStatus.ERROR
        self.save(update_fields=["fail_count", "status"])

    def reset_fail(self):
        self.fail_count = 0
        self.status = AccountStatus.ACTIVE
        self.save(update_fields=["fail_count", "status"])

    def rotate_proxy(self):
        from apps.proxies.models import Proxy, ProxyStatus
        new_proxy = Proxy.objects.filter(
            is_active=True,
            status=ProxyStatus.ACTIVE
        ).exclude(id=self.proxy_id if self.proxy else None).order_by('?').first()

        if new_proxy:
            self.proxy = new_proxy
            self.save(update_fields=['proxy'])
            return True
        return False
