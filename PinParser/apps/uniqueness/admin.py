from django import forms
from django.contrib import admin
from django.utils.html import format_html, format_html_join
from loguru import logger
from openai import OpenAI, AuthenticationError, NotFoundError, PermissionDeniedError

from .models import (
    UniquenessConfig,
    ModelProvider,
    DEFAULT_OPENAI_MODEL,
    OPENAI_MODEL_SUGGESTIONS,
)


class ModelSuggestionsInput(forms.TextInput):
    """Текстове поле з підказками: можна вибрати зі списку або ввести свою модель."""

    def __init__(self, suggestions, attrs=None):
        super().__init__(attrs)
        self.suggestions = suggestions

    def render(self, name, value, attrs=None, renderer=None):
        list_id = f"{name}_suggestions"
        attrs = {**(attrs or {}), "list": list_id, "autocomplete": "off"}
        options = format_html_join("", '<option value="{}">', ((s,) for s in self.suggestions))
        return format_html(
            '{}<datalist id="{}">{}</datalist>',
            super().render(name, value, attrs, renderer),
            list_id,
            options,
        )


class UniquenessConfigForm(forms.ModelForm):
    class Meta:
        model = UniquenessConfig
        fields = "__all__"
        widgets = {
            "openai_model": ModelSuggestionsInput(OPENAI_MODEL_SUGGESTIONS),
        }

    def clean(self):
        cleaned_data = super().clean()

        if self.errors or cleaned_data.get("model_provider") != ModelProvider.OPENAI:
            return cleaned_data

        checked_fields = {"model_provider", "openai_model", "openai_api_key"}
        if self.instance.pk and not checked_fields & set(self.changed_data):
            return cleaned_data

        self._check_openai_model(
            model=cleaned_data.get("openai_model", "").strip() or DEFAULT_OPENAI_MODEL,
            api_key=cleaned_data.get("openai_api_key", ""),
        )
        return cleaned_data

    def _check_openai_model(self, model: str, api_key: str):
        """Перевіряє, що модель існує і доступна для ключа, щоб не дізнаватись про це посеред задачі."""
        if not api_key:
            # Missing key is reported by UniquenessConfig.clean()
            return
        try:
            client = OpenAI(api_key=api_key, timeout=10, max_retries=0)
            client.models.retrieve(model)
        except AuthenticationError:
            self.add_error("openai_api_key", "OpenAI відхилив цей API ключ.")
        except (NotFoundError, PermissionDeniedError):
            self.add_error("openai_model", f"Модель '{model}' не існує або недоступна для цього API ключа.")
        except Exception as e:
            # Network issues shouldn't block saving the config
            logger.warning(f"[UNIQUENESS] Could not verify OpenAI model '{model}': {e}")


@admin.register(UniquenessConfig)
class UniquenessConfigAdmin(admin.ModelAdmin):
    form = UniquenessConfigForm

    def has_module_permission(self, request):
        return request.user.is_superuser

    list_display = ('id', 'name', 'is_active', 'model_provider', 'get_model', 'created_at')
    list_editable = ('is_active',)
    list_filter = ('is_active', 'model_provider')
    search_fields = ('name',)

    def get_model(self, obj):
        """Відображає модель на основі провайдера"""
        return obj.model
    get_model.short_description = 'Модель'
