from redis import Redis
from rq import Connection, Queue, Worker

from app.config import settings


def main() -> None:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL must be configured before starting a durable worker")
    connection = Redis.from_url(settings.redis_url)
    with Connection(connection):
        worker = Worker([Queue("forge-reviews")], name="forge-review-worker")
        worker.work()


if __name__ == "__main__":
    main()
