from celery import shared_task

from apps.uniqueness.models import UniquenessConfig
from apps.uniqueness.services.ai_uniqueness_service import AIUniquenessService
from apps.uniqueness.services.slug_service import SlugService
from apps.results.models import PinResult

@shared_task
def run_uniqueness(task_id: int):
    config = UniquenessConfig.objects.filter(
        is_active=True
    ).first()

    if not config:
        return
    
    qs = PinResult.objects.filter(
        task_id=task_id,
        utitle__isnull=True,
    )

    service = AIUniquenessService(config)
    service.process_queryset(qs)

@shared_task
def generate_slugs(task_id: int):
    qs = PinResult.objects.filter(
        task_id=task_id,
        slug_url__isnull=True,
        utitle__isnull=False,
    )

    for pin in qs.iterator(chunk_size=200):
        pin.slug_url = SlugService.build_slug_url(
            pin_id=None,
            utitle=pin.utitle,
            base_url="xxx"
        )
        pin.save(update_fields=["slug_url"])