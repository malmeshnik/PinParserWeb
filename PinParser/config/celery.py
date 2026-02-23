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

app.conf.broker_transport_options = {
    "visibility_timeout": 14400,
}

app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True

app.autodiscover_tasks()