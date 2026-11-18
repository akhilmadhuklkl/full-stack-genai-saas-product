import json


def test_authenticated_review_workflow_to_export(client, monkeypatch) -> None:
    from app.ai.ollama import ReviewFindingResult, ReviewResult

    class FakeReviewService:
        def review(self, project_name, files, prompt_version, review_instructions):
            return ReviewResult(
                summary=f"Reviewed {project_name}.",
                findings=[
                    ReviewFindingResult(
                        severity="high",
                        file_path=files[0][0],
                        line_number=1,
                        title="Example issue",
                        explanation="The example contains a risky operation.",
                        recommendation="Use a safer implementation.",
                    )
                ],
            )

    monkeypatch.setattr("app.main.review_service", FakeReviewService())
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "workflow@example.com", "password": "StrongPass123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    created = client.post(
        "/api/v1/reviews",
        headers=headers,
        json={
            "project_name": "workflow-project",
            "files": [{"path": "app.py", "content": "dangerous()"}],
        },
    )
    review_id = created.json()["review_id"]

    completed = client.post(f"/api/v1/reviews/{review_id}/run", headers=headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["findings"][0]["severity"] == "high"

    details = client.get(f"/api/v1/reviews/{review_id}", headers=headers)
    assert details.status_code == 200
    assert details.json()["summary"] == "Reviewed workflow-project."

    exported_json = client.get(
        f"/api/v1/reviews/{review_id}/export?format=json", headers=headers
    )
    assert exported_json.status_code == 200
    assert json.loads(exported_json.text)["findings"][0]["title"] == "Example issue"

    exported_markdown = client.get(
        f"/api/v1/reviews/{review_id}/export?format=markdown", headers=headers
    )
    assert exported_markdown.status_code == 200
    assert "# Forge Review" in exported_markdown.text
    assert "Example issue" in exported_markdown.text
