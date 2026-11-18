import logging
from concurrent.futures import ThreadPoolExecutor

from redis import Redis
from rq import Queue

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


def enqueue_review(review_id: int):
    """Enqueue a review durably, or use the local fallback in development."""
    queue = get_review_queue()
    if queue is not None:
        return queue.enqueue(process_review, review_id, job_timeout=900, result_ttl=86400)
    return fallback_executor.submit(process_review, review_id)
