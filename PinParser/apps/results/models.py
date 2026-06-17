from django.db import models

# Create your models here.
class PinResult(models.Model):
    task = models.ForeignKey(
        "tasks.ParseTask",
        on_delete=models.CASCADE,
        related_name="results",
        verbose_name="Завдання",
    )

    keyword = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Ключове слово",
    )

    pin_url = models.URLField(
        max_length=500,
        db_index=True,
        verbose_name="URL піна",
    )

    pin_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="ID піна",
    )

    title = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    utitle = models.TextField(
        blank=True,
        null=True,
        verbose_name="Унікалізований title",
    )

    udescription = models.TextField(
        blank=True,
        null=True,
        verbose_name="Унікалізований description",
    )

    slug_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="Slug URL",
    )

    image_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
    )

    local_image = models.ImageField(
        upload_to="pins/",
        blank=True,
        null=True,
        verbose_name="Локальне фото",
    )

    alt_text = models.TextField(blank=True, null=True)

    domain = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    annotation = models.TextField(blank=True, null=True)

    saves = models.PositiveIntegerField(blank=True, null=True)

    pinner_username = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    creation_date = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Дата створення (Pinterest)",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата збереження",
    )

    class Meta:
        verbose_name = "Результат піна"
        verbose_name_plural = "Результати пінів"

        indexes = [
            models.Index(fields=["pin_url"]),
            models.Index(fields=["keyword"]),
            models.Index(fields=["pinner_username"]),
        ]

        unique_together = ("task", "pin_url")

    def __str__(self):
        return f"{self.pin_url}"
