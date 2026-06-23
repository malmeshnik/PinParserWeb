from django.db import models
from django.utils.translation import gettext_lazy as _

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
    message = models.TextField(verbose_name=_("Сообщение"))
    level = models.CharField(max_length=20, default='ERROR', verbose_name=_("Уровень"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата создания"))

    class Meta:
        verbose_name = _("Лог ошибок")
        verbose_name_plural = _("Логи ошибок")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.created_at} - {self.level} - {self.message[:50]}"
