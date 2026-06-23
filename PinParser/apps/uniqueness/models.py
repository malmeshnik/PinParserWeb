from django.db import models
from django.utils.translation import gettext_lazy as _

# Create your models here.
class UniquenessConfig(models.Model):
    is_active = models.BooleanField(default=True, verbose_name=_("Активен"))

    openai_api_key = models.CharField(
        max_length=255,
        verbose_name=_("OpenAI API ключ"),
    )

    model = models.CharField(
        max_length=100,
        default="gpt-4o-mini",
        verbose_name=_("OpenAI модель"),
    )

    max_tokens_title = models.PositiveSmallIntegerField(default=100, verbose_name=_("Максимальное количество токенов для заголовка"))
    max_tokens_description = models.PositiveSmallIntegerField(default=400, verbose_name=_("Максимальное количество токенов для описания"))

    temperature = models.FloatField(default=1.0, verbose_name=_("Температура"))

    prompt_template = models.TextField(
        verbose_name=_("Промпт"),
        default=(
            "Uniquify the following Pinterest pin content. "
            "Return ONLY a JSON object with 'title' and 'description' keys.\n\n"
            "Original Title: {{title}}\n"
            "Original Description: {{description}}\n"
            "Alt Text: {{alt_text}}\n"
            "Annotation: {{annotation}}\n"
        ),
        help_text=(
            _("Доступные переменные:\n"
            "{{title}}, {{description}}, {{alt_text}}, {{annotation}}, {{domain}}, {{image_url}}, {{keyword}}")
        ),
    )

    use_title = models.BooleanField(default=True, verbose_name=_("Использовать заголовок"))
    use_description = models.BooleanField(default=True, verbose_name=_("Использовать описание"))
    use_alt_text = models.BooleanField(default=True, verbose_name=_("Использовать Alt текст"))
    use_annotation = models.BooleanField(default=True, verbose_name=_("Использовать аннотацию"))
    use_domain = models.BooleanField(default=False, verbose_name=_("Использовать домен"))
    use_image_url = models.BooleanField(default=False, verbose_name=_("Использовать URL изображения"))
    use_keyword = models.BooleanField(default=True, verbose_name=_("Использовать ключевое слово"))

    max_requests_per_minute = models.PositiveSmallIntegerField(
        default=450,
        verbose_name=_("Максимальное количество запросов в минуту")
    )

    max_workers = models.PositiveSmallIntegerField(
        default=5,
        verbose_name=_("Количество потоков"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Дата сохранения"))

    class Meta:
        verbose_name = _("Уникализация")
        verbose_name_plural = _("Уникализация")

    def __str__(self):
        return _("Уникализация #%(id)s") % {"id": self.id}
