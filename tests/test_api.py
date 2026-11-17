from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_review_returns_queued_review() -> None:
    auth = client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "password": "password-123"},
    )
    response = client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Bearer {auth.json()['access_token']}"},
        json={
            "project_name": "demo-project",
            "files": [{"path": "app.py", "content": "print('hello')"}],
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["review_id"].isdigit()
    assert body["status"] == "queued"
    assert body["message"] == "Review accepted for 1 file(s)."


def test_create_review_rejects_empty_file_list() -> None:
    auth = client.post(
        "/api/v1/auth/register",
        json={"email": "empty@example.com", "password": "password-123"},
    )
    response = client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Bearer {auth.json()['access_token']}"},
        json={"project_name": "demo-project", "files": []},
    )

    assert response.status_code == 422


def test_missing_project_returns_not_found() -> None:
    auth = client.post(
        "/api/v1/auth/register",
        json={"email": "missing@example.com", "password": "password-123"},
    )
    response = client.get(
        "/api/v1/projects/999999",
        headers={"Authorization": f"Bearer {auth.json()['access_token']}"},
    )

    assert response.status_code == 404


def test_projects_require_authentication() -> None:
    response = client.get("/api/v1/projects")

    assert response.status_code == 401


def test_project_creation_requires_authentication() -> None:
    response = client.post("/api/v1/projects", json={"name": "demo"})

    assert response.status_code == 401


def test_file_creation_requires_authentication() -> None:
    response = client.post(
        "/api/v1/projects/1/files",
        json={"path": "app.py", "content": "print('hello')"},
    )

    assert response.status_code == 401


def test_review_status_update_requires_authentication() -> None:
    response = client.patch(
        "/api/v1/reviews/1/status",
        json={"status": "processing"},
    )

    assert response.status_code == 401


def test_validation_errors_use_safe_stable_shape(client) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "password" in response.json()["fields"]
