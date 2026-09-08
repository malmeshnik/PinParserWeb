from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.results.models import PinResult
from apps.tasks.models import ParseTask
from apps.uniqueness.tasks import retry_uniqueness


class Command(BaseCommand):
    help = 'Retry uniqueness processing for pins without utitle'

    def add_arguments(self, parser):
        parser.add_argument(
            'task_id',
            type=int,
            help='Task ID to retry uniqueness for'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force retry even for completed tasks'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of pins to retry'
        )

    def handle(self, *args, **options):
        task_id = options['task_id']
        force = options['force']
        limit = options['limit']

        try:
            task = ParseTask.objects.get(id=task_id)
        except ParseTask.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Task {task_id} does not exist')
            )
            return

        # Find pins without utitle
        qs = PinResult.objects.filter(
            task_id=task_id,
            utitle__isnull=True,
        )

        if limit:
            qs = qs[:limit]

        pin_ids = list(qs.values_list('id', flat=True))
        count = len(pin_ids)

        if count == 0:
            self.stdout.write(
                self.style.SUCCESS('No pins need retry - all have utitle')
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f'Found {count} pins without utitle for task {task_id}'
            )
        )

        if not force:
            confirm = input('Do you want to schedule retry task? [y/N]: ')
            if confirm.lower() != 'y':
                self.stdout.write(self.style.WARNING('Cancelled'))
                return

        # Schedule retry task
        result = retry_uniqueness.apply_async(
            args=[task_id, pin_ids],
            countdown=5
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Retry task scheduled: {result.id}\n'
                f'Will process {count} pins in 5 seconds'
            )
        )
