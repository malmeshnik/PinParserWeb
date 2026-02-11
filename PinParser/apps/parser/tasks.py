from celery import shared_task
from loguru import logger

from apps.parser.services.pipeline import PinterestParsePipeline
from apps.proxies.models import Proxy
from apps.accounts.models import PinterestAccount

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 10},
    retry_backoff=True,
)
def run_pinterest_pipeline(
    self,
    keywords: list[str],
    proxy_id: int | None = None,
    account_id: int | None = None,
    max_pins: int | None = None,
):
    logger.info(
        f"[CELERY] Starting Pinterest pipeline | "
        f"keywords={keywords}"
    )

    proxy = None
    if proxy_id:
        proxy = Proxy.objects.filter(id=proxy_id).first()

    account = None

    pipeline = PinterestParsePipeline(
        keywords=keywords,
        proxy=proxy,
        account=None,
        max_pins=max_pins,
    )

    results = pipeline.run()

    logger.info(
        f"[CELERY] Finished | pins={len(results)}"
    )

    return {
        "keywords": keywords,
        "pins": len(results),
    }