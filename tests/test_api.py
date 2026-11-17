from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_review_returns_queued_review() -> None:
    response = client.post(
        "/api/v1/reviews",
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
    response = client.post(
        "/api/v1/reviews",
        json={"project_name": "demo-project", "files": []},
    )

    assert response.status_code == 422
