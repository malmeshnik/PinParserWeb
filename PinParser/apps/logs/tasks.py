from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import ErrorLog


@shared_task
def cleanup_old_logs():
    cutoff_date = timezone.now() - timedelta(days=30)
    deleted_count, _ = ErrorLog.objects.filter(created_at__lt=cutoff_date).delete()
    return f"Deleted {deleted_count} old logs"
