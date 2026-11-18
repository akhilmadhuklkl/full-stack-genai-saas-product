from app.main import app


def test_openapi_contains_review_lifecycle_routes() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/reviews/{review_id}/enqueue" in paths
    assert "/api/v1/reviews/{review_id}/retry" in paths
    assert "/api/v1/reviews/{review_id}/export" in paths
    assert "post" in paths["/api/v1/reviews/{review_id}/retry"]


def test_openapi_documents_review_history_parameters() -> None:
    operation = app.openapi()["paths"]["/api/v1/projects/{project_id}/reviews"]["get"]
    parameter_names = {parameter["name"] for parameter in operation["parameters"]}

    assert {"status", "search", "page", "page_size"}.issubset(parameter_names)
