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
        json={"email": "test@example.com", "password": "StrongPass123"},
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
        json={"email": "empty@example.com", "password": "StrongPass123"},
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
        json={"email": "missing@example.com", "password": "StrongPass123"},
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


def test_usage_requires_authentication(client) -> None:
    response = client.get("/api/v1/me/usage")

    assert response.status_code == 401


def test_job_status_requires_authentication(client) -> None:
    response = client.get("/api/v1/jobs/1")

    assert response.status_code == 401


def test_enqueue_review_returns_job_metadata(client, monkeypatch) -> None:
    monkeypatch.setattr("app.main.enqueue_review", lambda review_id: None)
    auth = client.post(
        "/api/v1/auth/register",
        json={"email": "queue@example.com", "password": "StrongPass123"},
    )
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
    review = client.post(
        "/api/v1/reviews",
        headers=headers,
        json={
            "project_name": "queue-project",
            "files": [{"path": "app.py", "content": "print('hello')"}],
        },
    )

    response = client.post(
        f"/api/v1/reviews/{review.json()['review_id']}/enqueue",
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["attempt_count"] == 0
    assert response.json()["started_at"] is None


def test_enqueue_review_status_can_be_polled(client, monkeypatch) -> None:
    monkeypatch.setattr("app.main.enqueue_review", lambda review_id: None)
    auth = client.post(
        "/api/v1/auth/register",
        json={"email": "poll@example.com", "password": "StrongPass123"},
    )
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
    review = client.post(
        "/api/v1/reviews",
        headers=headers,
        json={
            "project_name": "poll-project",
            "files": [{"path": "app.py", "content": "print('hello')"}],
        },
    )
    queued = client.post(
        f"/api/v1/reviews/{review.json()['review_id']}/enqueue",
        headers=headers,
    ).json()

    response = client.get(f"/api/v1/jobs/{queued['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["review_id"] == int(review.json()["review_id"])
    assert response.json()["status"] == "queued"


def test_retry_rejects_non_failed_review(client, monkeypatch) -> None:
    monkeypatch.setattr("app.main.enqueue_review", lambda review_id: None)
    auth = client.post(
        "/api/v1/auth/register",
        json={"email": "retry@example.com", "password": "StrongPass123"},
    )
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
    review = client.post(
        "/api/v1/reviews",
        headers=headers,
        json={
            "project_name": "retry-project",
            "files": [{"path": "app.py", "content": "print('hello')"}],
        },
    )
    review_id = review.json()["review_id"]
    client.post(f"/api/v1/reviews/{review_id}/enqueue", headers=headers)

    response = client.post(f"/api/v1/reviews/{review_id}/retry", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "Only failed reviews can be retried"


def test_archive_upload_requires_authentication(client) -> None:
    response = client.post(
        "/api/v1/projects/1/archive",
        files={"archive": ("project.zip", b"not-a-zip", "application/zip")},
    )

    assert response.status_code == 401


def test_weak_password_is_rejected(client) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "secure@example.com", "password": "password-123"},
    )

    assert response.status_code == 422


def test_direct_file_path_traversal_is_rejected(client) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "paths@example.com", "password": "StrongPass123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "safe"})
    project_id = project.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/files",
        headers=headers,
        json={"path": "../secret.txt", "content": "private"},
    )

    assert response.status_code == 422


def test_users_cannot_read_each_others_projects(client) -> None:
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "StrongPass123"},
    )
    second = client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "StrongPass123"},
    )
    first_headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    project = client.post(
        "/api/v1/projects", headers=first_headers, json={"name": "private-project"}
    )

    response = client.get(
        f"/api/v1/projects/{project.json()['id']}", headers=second_headers
    )

    assert response.status_code == 404


def test_account_requires_authentication(client) -> None:
    response = client.get("/api/v1/me")

    assert response.status_code == 401


def test_basic_health_endpoint_is_public(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_endpoint_is_public(client) -> None:
    response = client.get("/api/v1/version")

    assert response.status_code == 200
    assert response.json()["version"] == "0.1.0"


def test_project_stats_requires_authentication(client) -> None:
    response = client.get("/api/v1/projects/1/stats")

    assert response.status_code == 401
