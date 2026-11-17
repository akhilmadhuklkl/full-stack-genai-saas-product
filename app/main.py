from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectFile, Review, User
from app.db.session import create_tables, get_db
from app.schemas.review import (
    ProjectFileResponse,
    ProjectResponse,
    ReviewDetailResponse,
    ReviewFindingResponse,
    ReviewRequest,
    ReviewResponse,
    ReviewSummaryResponse,
)


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


@app.get("/api/v1/projects", response_model=list[ProjectResponse], tags=["projects"])
def list_projects(database: Session = Depends(get_db)) -> list[ProjectResponse]:
    """List projects belonging to the local development user."""
    user = database.query(User).filter(User.email == "local-dev@example.com").one_or_none()
    if user is None:
        return []

    return [
        ProjectResponse(
            id=project.id,
            name=project.name,
            files=[ProjectFileResponse(id=file.id, path=file.path) for file in project.files],
        )
        for project in user.projects
    ]


@app.get("/api/v1/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
def get_project(project_id: int, database: Session = Depends(get_db)) -> ProjectResponse:
    """Return one project and its file paths."""
    project = database.query(Project).filter(Project.id == project_id).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectResponse(
        id=project.id,
        name=project.name,
        files=[ProjectFileResponse(id=file.id, path=file.path) for file in project.files],
    )


@app.get(
    "/api/v1/projects/{project_id}/reviews",
    response_model=list[ReviewSummaryResponse],
    tags=["reviews"],
)
def list_reviews(
    project_id: int, database: Session = Depends(get_db)
) -> list[ReviewSummaryResponse]:
    """List review runs for one project."""
    project = database.query(Project).filter(Project.id == project_id).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return [
        ReviewSummaryResponse(
            id=review.id,
            project_id=review.project_id,
            status=review.status,
            summary=review.summary,
        )
        for review in project.reviews
    ]


@app.get("/api/v1/reviews/{review_id}", response_model=ReviewDetailResponse, tags=["reviews"])
def get_review(review_id: int, database: Session = Depends(get_db)) -> ReviewDetailResponse:
    """Return one review and its structured findings."""
    review = database.query(Review).filter(Review.id == review_id).one_or_none()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    return ReviewDetailResponse(
        id=review.id,
        project_id=review.project_id,
        status=review.status,
        summary=review.summary,
        findings=[
            ReviewFindingResponse(
                id=finding.id,
                severity=finding.severity,
                file_path=finding.file_path,
                line_number=finding.line_number,
                title=finding.title,
                explanation=finding.explanation,
                recommendation=finding.recommendation,
            )
            for finding in review.findings
        ],
    )
