import pytest

from app.limits import LoginAttemptLimiter


def test_email_action_limit_blocks_repeated_requests() -> None:
    limiter = LoginAttemptLimiter(max_attempts=2)
    limiter.record_failure("reset@example.com")
    limiter.record_failure("reset@example.com")

    with pytest.raises(Exception, match="Too many failed login attempts"):
        limiter.check("reset@example.com")
