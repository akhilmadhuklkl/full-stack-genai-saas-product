import logging

import httpx

from app.config import settings

logger = logging.getLogger("forge_review.email")


class EmailDeliveryError(RuntimeError):
    """Raised when transactional email cannot be delivered."""


def send_email(to: str, subject: str, text: str) -> None:
    """Send transactional email through Resend or log a local development message."""
    if settings.email_provider == "console":
        logger.info("local_email to=%s subject=%s body=%s", to, subject, text)
        return
    if settings.email_provider != "resend" or not settings.resend_api_key:
        raise EmailDeliveryError("Email delivery is not configured")
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "text": text},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise EmailDeliveryError("Transactional email delivery failed") from error
