from app.security import create_access_token, get_user_id_from_token


def test_access_token_contains_expiry() -> None:
    token = create_access_token(42, ttl_seconds=60)

    assert get_user_id_from_token(token) == 42


def test_expired_access_token_is_rejected() -> None:
    token = create_access_token(42, ttl_seconds=-1)

    assert get_user_id_from_token(token) is None
