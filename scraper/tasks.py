import logging
from typing import Optional
import httpx
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta

from .models import ScrapingSource, ScrapedResult
from .scraper import WebsiteScraper

logger = logging.getLogger(__name__)

# Must be longer than the task soft_time_limit (600s) so the lock
# expires automatically even if the worker is killed
_LOCK_TIMEOUT_SECONDS: int = 60 * 11  # 11 minutes


@shared_task(
    bind=True,
    acks_late=True,
    task_reject_on_worker_lost=True,
    soft_time_limit=600,
    autoretry_for=(httpx.RequestError,),
    retry_backoff=True,
    retry_jitter=True,  # Prevents thundering-herd on mass retries
    max_retries=3,
)
def perform_scraping_task(self, source_id: int) -> Optional[str]:
    """
    Worker task: fetch and parse data for a single source.

    Uses a Redis distributed lock (cache.add) to prevent duplicate runs
    when the heartbeat fires before the previous scrape finishes.
    """
    lock_key: str = f"scraping_lock_source_{source_id}"
    # cache.add() is atomic — returns True only if the key did not exist
    lock_acquired: bool = cache.add(
        lock_key, self.request.id, timeout=_LOCK_TIMEOUT_SECONDS
    )

    if not lock_acquired:
        logger.warning(
            f"[SKIP] Source {source_id} is already being scraped (lock exists). "
            f"Running task ID: {cache.get(lock_key)}"
        )
        return f"Skipped: duplicate task for source {source_id}"

    try:
        # Source may have been deleted between enqueue and execution
        source = ScrapingSource.objects.get(id=source_id)
    except ScrapingSource.DoesNotExist:
        cache.delete(lock_key)
        logger.error(f"Source with ID {source_id} does not exist.")
        return None

    if not source.is_active:
        cache.delete(lock_key)
        logger.info(f"Source '{source.name}' is inactive. Skipping.")
        return None

    scraper = WebsiteScraper()

    try:
        scraped_data: dict = scraper.scrape(
            url=source.url,
            rules=source.rules,
            extraction_type=source.extraction_type,
        )

        # Detect changes — fetch only the data column to avoid unnecessary joins
        previous: Optional[ScrapedResult] = (
            ScrapedResult.objects.filter(source=source)
            .order_by("-created_at")
            .only("data")
            .first()
        )
        if previous is None:
            has_changed: bool = True  # First scrape for this source
        else:
            has_changed = scraped_data != previous.data

        if has_changed:
            logger.info(f"[CHANGE] Data changed for '{source.name}'")
        else:
            logger.debug(f"[NO CHANGE] Data unchanged for '{source.name}'")

        ScrapedResult.objects.create(
            source=source, data=scraped_data, has_changed=has_changed
        )

        source.last_scraped_at = timezone.now()
        source.last_error = None
        source.save(update_fields=["last_scraped_at", "last_error"])

        logger.info(f"[OK] Successfully scraped: {source.name}")
        return f"Success: {source.name}"

    except Exception as e:
        error_msg: str = str(e)
        source.last_error = error_msg
        source.save(update_fields=["last_error"])
        logger.error(f"[ERROR] Scraping failed for '{source.name}': {error_msg}")
        raise e  # Re-raise so Celery can retry on httpx.RequestError

    finally:
        # Always release the lock, even on error or timeout
        cache.delete(lock_key)


@shared_task
def manager_heartbeat() -> str:
    """
    Dispatcher task: runs every minute via Celery Beat.

    Iterates active sources and enqueues a worker task for any source
    whose next scheduled scrape time has passed.

    Why a heartbeat instead of individual Beat entries?
    Each source has its own frequency_minutes set in the database.
    A static Beat schedule cannot handle that dynamically.
    """
    now = timezone.now()
    active_sources = ScrapingSource.objects.filter(is_active=True)
    tasks_dispatched: int = 0

    for source in active_sources:
        needs_scraping: bool
        if not source.last_scraped_at:
            needs_scraping = True
        else:
            next_scrape_time = source.last_scraped_at + timedelta(
                minutes=source.frequency_minutes
            )
            needs_scraping = now >= next_scrape_time

        if needs_scraping:
            # .delay() enqueues asynchronously and returns immediately
            perform_scraping_task.delay(source.id)
            tasks_dispatched += 1

    logger.info(f"[HEARTBEAT] Dispatched {tasks_dispatched} tasks.")
    return f"Dispatched {tasks_dispatched} tasks"
