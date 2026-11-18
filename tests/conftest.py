import os

os.environ["APP_ENV"] = "test"
os.environ["REDIS_URL"] = ""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.session import Base, get_db
    from app.main import app

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as database:
            yield database

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def fake_review_service(monkeypatch):
    class FakeReviewService:
        def review(self, project_name, files, prompt_version=None, review_instructions=None):
            from app.ai.ollama import ReviewFindingResult, ReviewResult

            return ReviewResult(
                summary=f"Reviewed {project_name} locally.",
                findings=[
                    ReviewFindingResult(
                        severity="medium",
                        file_path=files[0][0],
                        line_number=1,
                        title="Example maintainability finding",
                        explanation="This is a deterministic test finding.",
                        recommendation="Refactor the example code.",
                    )
                ],
            )

    monkeypatch.setattr("app.main.review_service", FakeReviewService())
