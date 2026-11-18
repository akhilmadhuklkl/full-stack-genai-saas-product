import pytest

from app.limits import LoginAttemptLimiter


def test_login_attempt_limiter_blocks_after_failures() -> None:
    limiter = LoginAttemptLimiter(max_attempts=2)
    limiter.record_failure("user@example.com")
    limiter.record_failure("user@example.com")

    with pytest.raises(Exception, match="Too many failed login attempts"):
        limiter.check("user@example.com")


def test_login_attempt_limiter_reset_allows_login() -> None:
    limiter = LoginAttemptLimiter(max_attempts=1)
    limiter.record_failure("user@example.com")
    limiter.reset("user@example.com")

    limiter.check("user@example.com")
