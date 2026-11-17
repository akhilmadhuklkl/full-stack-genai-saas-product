from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectFile, Review, ReviewFinding, User
from app.db.session import Base


def test_database_schema_contains_core_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())

    assert table_names == {"users", "projects", "project_files", "reviews", "review_findings"}


def test_review_relationships_store_project_context_and_findings() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="engineer@example.com", password_hash="test-hash")
        project = Project(name="demo-review", owner=user)
        project.files.append(ProjectFile(path="app.py", content="print('hello')"))
        review = Review(status="completed", project=project, summary="One finding")
        review.findings.append(
            ReviewFinding(
                severity="medium",
                file_path="app.py",
                line_number=1,
                title="Example finding",
                explanation="The code should be reviewed.",
                recommendation="Add a safer implementation.",
            )
        )
        session.add(review)
        session.commit()

        saved_review = session.query(Review).one()
        assert saved_review.project.owner.email == "engineer@example.com"
        assert saved_review.project.files[0].path == "app.py"
        assert saved_review.findings[0].severity == "medium"
