from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock

import redis
from fastapi import HTTPException, status

from app.config import settings
from app.time import utcnow


class ReviewRateLimiter:
    """Process-local review limiter for the single-instance development app."""

    def __init__(self, max_requests: int = 10, window_minutes: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(minutes=window_minutes)
        self.requests: dict[int, deque[datetime]] = defaultdict(deque)
        self.lock = Lock()

    def check_and_record(self, user_id: int) -> None:
        now = utcnow()
        cutoff = now - self.window
        with self.lock:
            user_requests = self.requests[user_id]
            while user_requests and user_requests[0] <= cutoff:
                user_requests.popleft()
            if len(user_requests) >= self.max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Review rate limit exceeded. Try again later.",
                    headers={"Retry-After": str(int(self.window.total_seconds()))},
                )
            user_requests.append(now)


class LoginAttemptLimiter:
    """Process-local limiter for repeated failed login attempts."""

    def __init__(self, max_attempts: int = 5, window_minutes: int = 15):
        self.max_attempts = max_attempts
        self.window = timedelta(minutes=window_minutes)
        self.attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self.lock = Lock()
        self.redis_client = None
        if settings.redis_url:
            try:
                candidate = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                candidate.ping()
                self.redis_client = candidate
            except redis.RedisError:
                self.redis_client = None

    def check(self, email: str) -> None:
        if self.redis_client is not None:
            try:
                count = int(self.redis_client.get(self._key(email)) or 0)
                if count >= self.max_attempts:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many failed login attempts. Try again later.",
                        headers={"Retry-After": str(int(self.window.total_seconds()))},
                    )
                return
            except redis.RedisError:
                self.redis_client = None
        now = utcnow()
        cutoff = now - self.window
        with self.lock:
            attempts = self.attempts[email]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many failed login attempts. Try again later.",
                    headers={"Retry-After": str(int(self.window.total_seconds()))},
                )

    def record_failure(self, email: str) -> None:
        if self.redis_client is not None:
            try:
                key = self._key(email)
                count = self.redis_client.incr(key)
                if count == 1:
                    self.redis_client.expire(key, int(self.window.total_seconds()))
                return
            except redis.RedisError:
                self.redis_client = None
        with self.lock:
            self.attempts[email].append(utcnow())

    def reset(self, email: str) -> None:
        if self.redis_client is not None:
            try:
                self.redis_client.delete(self._key(email))
                return
            except redis.RedisError:
                self.redis_client = None
        with self.lock:
            self.attempts.pop(email, None)

    @staticmethod
    def _key(email: str) -> str:
        return f"forge:login-attempts:{email}"


class RedisReviewRateLimiter(ReviewRateLimiter):
    """Distributed limiter using Redis, with the local limiter as fallback."""

    def __init__(self, redis_url: str | None, max_requests: int = 10, window_minutes: int = 60):
        super().__init__(max_requests, window_minutes)
        self.redis_client = None
        if redis_url:
            try:
                candidate = redis.Redis.from_url(redis_url, decode_responses=True)
                candidate.ping()
                self.redis_client = candidate
            except redis.RedisError:
                self.redis_client = None

    def check_and_record(self, user_id: int) -> None:
        if self.redis_client is None:
            return super().check_and_record(user_id)
        key = f"forge:review-rate:{user_id}"
        try:
            count = self.redis_client.incr(key)
            if count == 1:
                self.redis_client.expire(key, int(self.window.total_seconds()))
            if count > self.max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Review rate limit exceeded. Try again later.",
                    headers={"Retry-After": str(int(self.window.total_seconds()))},
                )
        except redis.RedisError:
            self.redis_client = None
            super().check_and_record(user_id)


review_rate_limiter = RedisReviewRateLimiter(settings.redis_url)
login_attempt_limiter = LoginAttemptLimiter()
