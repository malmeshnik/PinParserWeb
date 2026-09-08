from django.db import models
from django.utils.translation import gettext_lazy as _

# Create your models here.
class ModelProvider(models.TextChoices):
    OPENAI = "openai", _("OpenAI (gpt-4o-mini)")
    DASHSCOPE = "dashscope", _("DashScope (qwen3.7-flash) - 15000 req/min")


class UniquenessConfig(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name=_("Название конфигурации"),
        default="Default Config",
    )

    is_active = models.BooleanField(default=True, verbose_name=_("Активен"))

    model_provider = models.CharField(
        max_length=20,
        choices=ModelProvider.choices,
        default=ModelProvider.OPENAI,
        verbose_name=_("Провайдер модели"),
    )

    openai_api_key = models.CharField(
        max_length=255,
        verbose_name=_("API ключ"),
        help_text=_("OpenAI API ключ или DashScope API ключ (DASHSCOPE_API_KEY)"),
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
            "{{title}}, {{description}}, {{alt_text}}, {{annotation}}, {{domain}}, {{image_url}}, {{keyword}}"
        ),
    )

    use_title = models.BooleanField(default=True)
    use_description = models.BooleanField(default=True)
    use_alt_text = models.BooleanField(default=True)
    use_annotation = models.BooleanField(default=True)
    use_domain = models.BooleanField(default=False)
    use_image_url = models.BooleanField(default=False)
    use_keyword = models.BooleanField(default=True)

    max_requests_per_minute = models.PositiveSmallIntegerField(
        default=450,
        verbose_name="Максимальна кількість запитів за хвилину",
        help_text=_("OpenAI: 450-500, DashScope (qwen): 10000-14000")
    )

    max_workers = models.PositiveSmallIntegerField(
        default=5,
        verbose_name="Кількість потоків",
        help_text=_("Рекомендовано: OpenAI 5-10, DashScope 50-100")
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата збереження")

    class Meta:
        verbose_name = "Унікалізація"
        verbose_name_plural = "Унікалізація"

    def __str__(self):
        return self.name or _("Уникализация #%(id)s") % {"id": self.id}

    @property
    def model(self):
        """Автоматично визначає модель на основі провайдера"""
        if self.model_provider == ModelProvider.DASHSCOPE:
            return "qwen3.7-flash"
        return "gpt-4o-mini"

    @property
    def base_url(self):
        """Автоматично визначає base_url на основі провайдера"""
        if self.model_provider == ModelProvider.DASHSCOPE:
            return "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
        return None
