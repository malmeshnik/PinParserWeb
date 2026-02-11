from django.db import models

class ErrorLog(models.Model):
    task = models.ForeignKey(
        'tasks.ParseTask',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logs',
        verbose_name="Завдання"
    )
    account = models.ForeignKey(
        'accounts.PinterestAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Аккаунт"
    )
    message = models.TextField(verbose_name="Повідомлення")
    level = models.CharField(max_length=20, default='ERROR', verbose_name="Рівень")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата створення")

    class Meta:
        verbose_name = "Лог помилок"
        verbose_name_plural = "Логи помилок"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.created_at} - {self.level} - {self.message[:50]}"
