import base64
import hashlib
import hmac
import secrets
import time

from app.config import settings

PASSWORD_ITERATIONS = 600_000
TOKEN_SEPARATOR = "."


def hash_password(password: str) -> str:
    """Hash a password with a unique salt using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PASSWORD_ITERATIONS
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password without exposing timing information."""
    try:
        salt_hex, digest_hex = stored_hash.split("$", maxsplit=1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), PASSWORD_ITERATIONS
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_access_token(user_id: int, ttl_seconds: int | None = None) -> str:
    """Create a signed token containing the user ID and expiration timestamp."""
    secret = settings.auth_secret.encode()
    expires_at = int(time.time()) + (
        settings.auth_token_ttl_seconds if ttl_seconds is None else ttl_seconds
    )
    payload = f"{user_id}:{expires_at}".encode()
    encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(secret, encoded_payload.encode(), hashlib.sha256).hexdigest()
    return f"{encoded_payload}{TOKEN_SEPARATOR}{signature}"


def get_user_id_from_token(token: str) -> int | None:
    """Validate a token signature and return its user ID."""
    try:
        encoded_payload, signature = token.split(TOKEN_SEPARATOR, maxsplit=1)
        secret = settings.auth_secret.encode()
        expected_signature = hmac.new(
            secret, encoded_payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        padded_payload = encoded_payload + "=" * (-len(encoded_payload) % 4)
        user_id, expires_at = base64.urlsafe_b64decode(padded_payload).decode().split(":")
        if int(expires_at) <= int(time.time()):
            return None
        return int(user_id)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
