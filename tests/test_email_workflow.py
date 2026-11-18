def test_email_verification_token_is_one_time_use(client, monkeypatch) -> None:
    delivered = {}

    def fake_send_email(to, subject, text):
        delivered["text"] = text

    monkeypatch.setattr("app.main.send_email", fake_send_email)
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "verify@example.com", "password": "StrongPass123"},
    )
    assert registration.status_code == 201
    raw_token = delivered["text"].split("token=", 1)[1]

    confirmed = client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": raw_token},
    )
    assert confirmed.status_code == 204
    reused = client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"token": raw_token},
    )
    assert reused.status_code == 400


def test_password_reset_request_is_generic_for_unknown_email(client, monkeypatch) -> None:
    monkeypatch.setattr("app.main.send_email", lambda *args, **kwargs: None)

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )

    assert response.status_code == 202
    assert response.json() == {
        "message": "If the account exists, a password reset email has been sent."
    }


def test_password_reset_changes_password(client, monkeypatch) -> None:
    delivered = {}

    def fake_send_email(to, subject, text):
        delivered["text"] = text

    monkeypatch.setattr("app.main.send_email", fake_send_email)
    client.post(
        "/api/v1/auth/register",
        json={"email": "reset@example.com", "password": "StrongPass123"},
    )
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    assert response.status_code == 202
    token = delivered["text"].split("token=", 1)[1]

    confirmed = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "NewStrongPass123"},
    )
    assert confirmed.status_code == 204
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "NewStrongPass123"},
    )
    assert login.status_code == 200
