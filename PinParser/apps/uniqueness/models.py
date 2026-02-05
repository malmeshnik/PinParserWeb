from django.db import models

# Create your models here.
class UniquenessConfig(models.Model):
    is_active = models.BooleanField(default=True, verbose_name="Активний")

    openai_api_key = models.CharField(
        max_length=255,
        verbose_name="OpenAI API key",
    )

    model = models.CharField(
        max_length=100,
        default="gpt-4o-mini",
        verbose_name="OpenAI model",
    )

    max_tokens_title = models.PositiveSmallIntegerField(default=100, verbose_name="Максимальна кількіть токенів для title")
    max_tokens_description = models.PositiveSmallIntegerField(default=400, verbose_name="Максимальна кількіть токенів для desctription")

    temperature = models.FloatField(default=1.0)

    prompt_template = models.TextField(
        verbose_name="Промпт",
        default=(
            "Uniquify the following Pinterest pin content. "
            "Return ONLY a JSON object with 'title' and 'description' keys.\n\n"
            "Original Title: {{title}}\n"
            "Original Description: {{description}}\n"
            "Alt Text: {{alt_text}}\n"
            "Annotation: {{annotation}}\n"
        ),
        help_text=(
            "Доступні змінні:\n"
            "{{title}}, {{description}}, {{alt_text}}, {{annotation}}, {{domain}}, {{image_url}}"
        ),
    )

    use_title = models.BooleanField(default=True)
    use_description = models.BooleanField(default=True)
    use_alt_text = models.BooleanField(default=True)
    use_annotation = models.BooleanField(default=True)
    use_domain = models.BooleanField(default=False)
    use_image_url = models.BooleanField(default=False)

    max_requests_per_minute = models.PositiveSmallIntegerField(
        default=450,
        verbose_name="Максимальна кількість запитів за хвилину"
    )

    max_workers = models.PositiveSmallIntegerField(
        default=5,
        verbose_name="Кількість потококів",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата збереження")

    class Meta:
        verbose_name = "Унікалізація"
        verbose_name_plural = "Унікалізація"

    def __str__(self):
        return f"Унікалізація #{self.id}"