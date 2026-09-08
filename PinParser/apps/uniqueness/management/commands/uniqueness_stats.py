from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from apps.results.models import PinResult
from apps.tasks.models import ParseTask


class Command(BaseCommand):
    help = 'Show uniqueness processing statistics for a task'

    def add_arguments(self, parser):
        parser.add_argument(
            'task_id',
            type=int,
            help='Task ID to check statistics for'
        )

    def handle(self, *args, **options):
        task_id = options['task_id']

        try:
            task = ParseTask.objects.get(id=task_id)
        except ParseTask.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Task {task_id} does not exist')
            )
            return

        # Get statistics
        stats = PinResult.objects.filter(task_id=task_id).aggregate(
            total=Count('id'),
            with_utitle=Count('id', filter=Q(utitle__isnull=False)),
            without_utitle=Count('id', filter=Q(utitle__isnull=True)),
        )

        total = stats['total']
        success = stats['with_utitle']
        failed = stats['without_utitle']
        success_rate = (success / total * 100) if total > 0 else 0

        self.stdout.write(
            self.style.SUCCESS(f'\nUniqueness Statistics for Task {task_id}:')
        )
        self.stdout.write(f'  Task status: {task.get_status_display()}')
        self.stdout.write(f'  Total pins: {total}')
        self.stdout.write(
            self.style.SUCCESS(f'  ✓ Successfully processed: {success}')
        )

        if failed > 0:
            self.stdout.write(
                self.style.ERROR(f'  ✗ Failed/Pending: {failed}')
            )
        else:
            self.stdout.write(f'  ✗ Failed/Pending: {failed}')

        self.stdout.write(f'  Success rate: {success_rate:.1f}%')

        if task.uniqueness_config:
            self.stdout.write(
                f'\n  Config: {task.uniqueness_config.name} '
                f'({task.uniqueness_config.model_provider})'
            )

        if failed > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'\n💡 Run "python manage.py retry_failed_uniqueness {task_id}" '
                    f'to retry failed pins'
                )
            )
