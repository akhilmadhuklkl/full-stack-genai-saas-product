import logging
from concurrent.futures import ThreadPoolExecutor

from redis import Redis
from rq import Queue, Retry

from app.config import settings
from app.jobs import process_review

logger = logging.getLogger("forge_review.queue")
fallback_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="review-fallback")


def get_review_queue() -> Queue | None:
    """Return the durable queue when Redis is configured and reachable."""
    if not settings.redis_url:
        return None
    try:
        client = Redis.from_url(settings.redis_url)
        client.ping()
        return Queue("forge-reviews", connection=client, default_timeout=900)
    except Exception:
        logger.warning("redis_queue_unavailable_using_local_fallback")
        return None


def get_queue_health() -> tuple[str, str]:
    """Return queue availability and a safe operational detail string."""
    if not settings.redis_url:
        return "degraded", "Redis is not configured; using local fallback worker"
    queue = get_review_queue()
    if queue is None:
        return "unavailable", "Redis review queue is unreachable"
    return "ok", f"Redis reachable; {len(queue)} review job(s) queued"


def enqueue_review(review_id: int):
    """Enqueue a review durably, or use the local fallback in development."""
    queue = get_review_queue()
    if queue is not None:
        job = queue.enqueue(
            process_review,
            review_id,
            job_timeout=900,
            result_ttl=86400,
            retry=Retry(max=2, interval=[10, 30]),
        )
        logger.info("review_enqueued review_id=%s queue_job_id=%s", review_id, job.id)
        return job
    future = fallback_executor.submit(process_review, review_id)
    future.add_done_callback(_log_fallback_failure)
    logger.info("review_enqueued_local_fallback review_id=%s", review_id)
    return future


def _log_fallback_failure(future) -> None:
    error = future.exception()
    if error is not None:
        logger.error("review_fallback_failed error=%s", error, exc_info=error)
