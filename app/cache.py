import json
from threading import Lock
from time import monotonic

import redis

from app.config import settings


class CacheBackend:
    """Use Redis when configured, otherwise use a bounded process-local cache."""

    def __init__(self, redis_url: str | None = None):
        self.client = None
        if redis_url:
            try:
                candidate = redis.Redis.from_url(redis_url, decode_responses=True)
                candidate.ping()
                self.client = candidate
            except redis.RedisError:
                self.client = None
        self.memory: dict[str, tuple[float, str]] = {}
        self.lock = Lock()

    def get_json(self, key: str):
        if self.client is not None:
            try:
                value = self.client.get(key)
                return json.loads(value) if value else None
            except redis.RedisError:
                self.client = None
        with self.lock:
            cached = self.memory.get(key)
            if cached is None or cached[0] <= monotonic():
                self.memory.pop(key, None)
                return None
            return json.loads(cached[1])

    def set_json(self, key: str, value, ttl_seconds: int = 60) -> None:
        encoded = json.dumps(value)
        if self.client is not None:
            try:
                self.client.setex(key, ttl_seconds, encoded)
                return
            except redis.RedisError:
                self.client = None
        with self.lock:
            self.memory[key] = (monotonic() + ttl_seconds, encoded)

    def delete(self, key: str) -> None:
        if self.client is not None:
            try:
                self.client.delete(key)
            except redis.RedisError:
                self.client = None
        with self.lock:
            self.memory.pop(key, None)


cache = CacheBackend(settings.redis_url)
