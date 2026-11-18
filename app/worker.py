import logging

from redis import Redis
from rq import Connection, Queue, Worker

from app.config import settings

logger = logging.getLogger("forge_review.worker")


class HeartbeatWorker(Worker):
    """RQ worker that publishes a short-lived liveness key for health checks."""

    heartbeat_key = "forge:worker:forge-review-worker"

    def heartbeat(self, *args, **kwargs):
        result = super().heartbeat(*args, **kwargs)
        self.connection.set(self.heartbeat_key, "alive", ex=60)
        return result


def main() -> None:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL must be configured before starting a durable worker")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    connection = Redis.from_url(settings.redis_url)
    with Connection(connection):
        worker = HeartbeatWorker([Queue("forge-reviews")], name="forge-review-worker")
        connection.set(HeartbeatWorker.heartbeat_key, "alive", ex=60)
        logger.info("review_worker_started queue=forge-reviews")
        worker.work()


if __name__ == "__main__":
    main()
