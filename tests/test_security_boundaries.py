def _register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPass123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_review(client, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/reviews",
        headers=headers,
        json={
            "project_name": "security-project",
            "files": [{"path": "app.py", "content": "print('safe')"}],
        },
    )
    return response.json()["review_id"]


def test_user_cannot_export_another_users_review(client) -> None:
    owner_headers = _register(client, "export-owner@example.com")
    other_headers = _register(client, "export-other@example.com")
    review_id = _create_review(client, owner_headers)

    response = client.get(
        f"/api/v1/reviews/{review_id}/export?format=json",
        headers=other_headers,
    )

    assert response.status_code == 404


def test_export_rejects_unknown_format(client) -> None:
    headers = _register(client, "format-owner@example.com")
    review_id = _create_review(client, headers)

    response = client.get(
        f"/api/v1/reviews/{review_id}/export?format=xml",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Format must be json or markdown"


def test_review_creation_enforces_user_rate_limit(client, monkeypatch) -> None:
    from app.limits import review_rate_limiter

    headers = _register(client, "rate-limit@example.com")
    review_rate_limiter.requests.clear()
    monkeypatch.setattr(review_rate_limiter, "max_requests", 1)
    _create_review(client, headers)

    response = client.post(
        "/api/v1/reviews",
        headers=headers,
        json={
            "project_name": "security-project",
            "files": [{"path": "app.py", "content": "print('safe')"}],
        },
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"]
