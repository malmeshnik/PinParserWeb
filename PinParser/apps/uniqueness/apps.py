from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UniquenessConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.uniqueness'
    verbose_name = _('Уникализация')
