import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("config")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.conf.task_routes = {
    "apps.tasks.tasks.*": {"queue": "parser"},
    "apps.uniqueness.tasks.*": {"queue": "ai"},
    "apps.results.tasks.*": {"queue": "export"},
}

app.autodiscover_tasks()