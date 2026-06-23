from django.core.management.base import BaseCommand
from django.db.models import Count
from apps.tasks.models import ParseTask

class Command(BaseCommand):
    help = 'Synchronize processed_urls with actual PinResult count for all tasks'

    def handle(self, *args, **options):
        tasks = ParseTask.objects.annotate(actual_count=Count('results'))

        updated_count = 0
        for task in tasks:
            if task.processed_urls != task.actual_count:
                task.processed_urls = task.actual_count
                task.save(update_fields=['processed_urls'])
                updated_count += 1
                self.stdout.write(f"Updated task #{task.id}: {task.processed_urls} results")

        self.stdout.write(self.style.SUCCESS(f"Successfully synchronized {updated_count} tasks"))