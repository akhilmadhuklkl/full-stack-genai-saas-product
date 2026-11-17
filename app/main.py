from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectFile, Review, User
from app.db.session import create_tables, get_db
from app.schemas.review import ReviewRequest, ReviewResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="GenAI Code Review Assistant API",
    version="0.1.0",
    description="Backend foundation for the AI-powered code review SaaS product.",
    lifespan=lifespan,
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a small readiness signal for local development and future deployment."""
    return {"status": "ok"}


@app.post("/api/v1/reviews", response_model=ReviewResponse, status_code=202, tags=["reviews"])
def create_review(request: ReviewRequest, database: Session = Depends(get_db)) -> ReviewResponse:
    """Persist a review request and return its initial processing state.

    Authentication is intentionally deferred. Until it is implemented, every local
    request belongs to one clearly named development user.
    """
    user = database.query(User).filter(User.email == "local-dev@example.com").one_or_none()
    if user is None:
        user = User(email="local-dev@example.com")
        database.add(user)
        database.flush()

    project = (
        database.query(Project)
        .filter(Project.owner_id == user.id, Project.name == request.project_name)
        .one_or_none()
    )
    if project is None:
        project = Project(owner=user, name=request.project_name)
        database.add(project)
        database.flush()

    for submitted_file in request.files:
        existing_file = (
            database.query(ProjectFile)
            .filter(ProjectFile.project_id == project.id, ProjectFile.path == submitted_file.path)
            .one_or_none()
        )
        if existing_file is None:
            project.files.append(
                ProjectFile(path=submitted_file.path, content=submitted_file.content)
            )
        else:
            existing_file.content = submitted_file.content

    review = Review(project=project, status="queued")
    database.add(review)
    database.commit()
    database.refresh(review)

    return ReviewResponse(
        review_id=str(review.id),
        status="queued",
        message=f"Review accepted for {len(request.files)} file(s).",
    )
