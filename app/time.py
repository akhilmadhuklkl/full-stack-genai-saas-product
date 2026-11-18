from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return a naive UTC timestamp compatible with the existing database schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
