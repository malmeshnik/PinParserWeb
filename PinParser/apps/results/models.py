from django.db import models
from django.utils.translation import gettext_lazy as _

# Create your models here.
class PinResult(models.Model):
    task = models.ForeignKey(
        "tasks.ParseTask",
        on_delete=models.CASCADE,
        related_name="results",
        verbose_name=_("Задание"),
    )

    keyword = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Ключевое слово"),
    )

    pin_url = models.URLField(
        max_length=500,
        db_index=True,
        verbose_name=_("URL пина"),
    )

    pin_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_("ID пина"),
    )

    title = models.TextField(blank=True, null=True, verbose_name=_("Заголовок"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Описание"))

    utitle = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Уникализированный заголовок"),
    )

    udescription = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Уникализированное описание"),
    )

    slug_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name=_("Slug URL"),
    )

    image_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name=_("URL изображения"),
    )

    local_image = models.ImageField(
        upload_to="pins/",
        blank=True,
        null=True,
        verbose_name=_("Локальное фото"),
    )

    alt_text = models.TextField(blank=True, null=True, verbose_name=_("Alt текст"))

    domain = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Домен"),
    )

    annotation = models.TextField(blank=True, null=True, verbose_name=_("Аннотация"))

    saves = models.PositiveIntegerField(blank=True, null=True, verbose_name=_("Сохранения"))

    pinner_username = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Имя пользователя"),
    )

    creation_date = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Дата создания (Pinterest)"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата сохранения"),
    )

    class Meta:
        verbose_name = _("Результат пина")
        verbose_name_plural = _("Результаты пинов")

        indexes = [
            models.Index(fields=["pin_url"]),
            models.Index(fields=["keyword"]),
            models.Index(fields=["pinner_username"]),
        ]

        unique_together = ("task", "pin_url")

    def __str__(self):
        return f"{self.pin_url}"
