from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

DEFAULT_OPENAI_MODEL = "gpt-4.1-nano-2025-04-14"

# Підказки для поля моделі в адмінці; можна ввести будь-яку іншу модель OpenAI
OPENAI_MODEL_SUGGESTIONS = [
    "gpt-4.1-nano-2025-04-14",
    "gpt-4.1-nano",
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5-nano",
    "gpt-5-mini",
    "gpt-5",
]

# Reasoning-моделі: не підтримують довільну temperature і витрачають токени на міркування
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


# Create your models here.
class ModelProvider(models.TextChoices):
    OPENAI = "openai", _("OpenAI - 450 req/min")
    DASHSCOPE = "dashscope", _("DashScope (qwen3.7-flash) - 15000 req/min")
    OMNIROUTE = "omniroute", _("OmniRoute")


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

    openai_model = models.CharField(
        max_length=255,
        blank=True,
        default=DEFAULT_OPENAI_MODEL,
        verbose_name=_("Модель OpenAI"),
        help_text=_(
            "Лише для OpenAI, наприклад gpt-4.1-mini або gpt-5-mini. "
            "Якщо порожньо — використовується gpt-4.1-nano-2025-04-14. "
            "Для reasoning-моделей (gpt-5, o-серія) temperature ігнорується."
        ),
    )

    omniroute_model = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Модель OmniRoute"),
        help_text=_("Лише для OmniRoute, наприклад kr/claude-sonnet-4.5. Якщо порожньо — використовується OMNIROUTE_MODEL із .env."),
    )

    openai_api_key = models.CharField(
        blank=True,
        max_length=255,
        verbose_name=_("API ключ"),
        help_text=_("Ключ OpenAI або DashScope. Для OmniRoute залиште порожнім: ключ береться з .env."),
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
    def api_key(self):
        if self.model_provider == ModelProvider.OMNIROUTE:
            return settings.OMNIROUTE_API_KEY
        return self.openai_api_key

    def clean(self):
        super().clean()
        if not self.api_key:
            raise ValidationError({
                "openai_api_key": _("Вкажіть API ключ; для OmniRoute налаштуйте OMNIROUTE_API_KEY у .env.")
            })

    @property
    def model(self):
        """Автоматично визначає модель на основі провайдера"""
        if self.model_provider == ModelProvider.OMNIROUTE:
            return self.omniroute_model.strip() or settings.OMNIROUTE_MODEL
        if self.model_provider == ModelProvider.DASHSCOPE:
            return "qwen3.7-flash"
        return self.openai_model.strip() or DEFAULT_OPENAI_MODEL

    @property
    def is_reasoning_model(self):
        return (
            self.model_provider == ModelProvider.OPENAI
            and self.model.startswith(REASONING_MODEL_PREFIXES)
        )

    @property
    def base_url(self):
        """Автоматично визначає base_url на основі провайдера"""
        if self.model_provider == ModelProvider.OMNIROUTE:
            return settings.OMNIROUTE_BASE_URL
        if self.model_provider == ModelProvider.DASHSCOPE:
            return "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
        return None
