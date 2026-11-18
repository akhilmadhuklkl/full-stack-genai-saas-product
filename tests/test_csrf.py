def test_bearer_api_requests_are_not_blocked_by_cookie_csrf(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
