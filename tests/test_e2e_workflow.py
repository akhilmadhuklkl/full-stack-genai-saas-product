def test_authenticated_review_workflow(client, fake_review_service) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "workflow@example.com", "password": "password-123"},
    )
    assert registration.status_code == 201
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    project = client.post("/api/v1/projects", headers=headers, json={"name": "payments"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    source_file = client.post(
        f"/api/v1/projects/{project_id}/files",
        headers=headers,
        json={"path": "payments.py", "content": "def charge(): pass"},
    )
    assert source_file.status_code == 201

    review = client.post(
        "/api/v1/reviews",
        headers=headers,
        json={
            "project_name": "payments",
            "files": [{"path": "payments.py", "content": "def charge(): pass"}],
        },
    )
    assert review.status_code == 202
    review_id = review.json()["review_id"]

    run = client.post(f"/api/v1/reviews/{review_id}/run", headers=headers)
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert run.json()["findings"][0]["severity"] == "medium"

    saved = client.get(f"/api/v1/reviews/{review_id}", headers=headers)
    assert saved.status_code == 200
    assert saved.json()["summary"] == "Reviewed payments locally."
