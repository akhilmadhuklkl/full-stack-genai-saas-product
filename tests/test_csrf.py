def test_bearer_api_requests_are_not_blocked_by_cookie_csrf(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_cookie_auth_requires_csrf_header_for_state_changes(client) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "csrf@example.com", "password": "StrongPass123"},
    )
    assert registration.status_code == 201
    assert "forge_access_token" in registration.cookies
    assert "forge_csrf_token" in registration.cookies

    blocked = client.post("/api/v1/projects", json={"name": "blocked"})
    assert blocked.status_code == 403

    csrf_token = registration.cookies["forge_csrf_token"]
    allowed = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf_token},
        json={"name": "allowed"},
    )
    assert allowed.status_code == 201
