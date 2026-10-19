import sys

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LogsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.logs'
    verbose_name = _('Логи')

    def ready(self):
        # Не збираємо помилки під час службових команд (міграції тощо)
        if len(sys.argv) > 1 and sys.argv[1] in ("makemigrations", "migrate", "collectstatic", "showmigrations"):
            return
        from .collector import install
        install()
