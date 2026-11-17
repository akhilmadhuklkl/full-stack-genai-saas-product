from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock

from fastapi import HTTPException, status


class ReviewRateLimiter:
    """Process-local review limiter for the single-instance development app."""

    def __init__(self, max_requests: int = 10, window_minutes: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(minutes=window_minutes)
        self.requests: dict[int, deque[datetime]] = defaultdict(deque)
        self.lock = Lock()

    def check_and_record(self, user_id: int) -> None:
        now = datetime.utcnow()
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


review_rate_limiter = ReviewRateLimiter()
