import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.ai.ollama import AIReviewError, OllamaReviewService
from app.cache import cache
from app.config import settings
from app.db.models import Project, ProjectFile, Review, ReviewFinding, UsageRecord, User
from app.db.session import create_tables, get_db
from app.dependencies import get_current_user
from app.limits import review_rate_limiter
from app.observability import (
    RequestLoggingMiddleware,
    unhandled_error_handler,
    validation_error_handler,
)
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from app.schemas.file import FileCreateRequest, FileResponse, FileUpdateRequest
from app.schemas.project import ProjectCreateRequest, ProjectUpdateRequest
from app.schemas.review import (
    ProjectFileResponse,
    ProjectResponse,
    ReviewDetailResponse,
    ReviewFindingResponse,
    ReviewRequest,
    ReviewResponse,
    ReviewSummaryResponse,
)
from app.schemas.review_result import FindingCreateRequest, ReviewStatusUpdateRequest
from app.schemas.usage import UsageResponse
from app.security import create_access_token, hash_password, verify_password

review_service = OllamaReviewService()


def project_cache_key(user_id: int) -> str:
    return f"forge:projects:{user_id}"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env != "test":
        create_tables()
    yield


app = FastAPI(
    title="GenAI Code Review Assistant API",
    version="0.1.0",
    description="Backend foundation for the AI-powered code review SaaS product.",
    lifespan=lifespan,
)
app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a small readiness signal for local development and future deployment."""
    return {"status": "ok"}


@app.post("/api/v1/auth/register", response_model=AuthResponse, status_code=201, tags=["auth"])
def register(request: RegisterRequest, database: Session = Depends(get_db)) -> AuthResponse:
    """Create a user account and return its access token."""
    email = request.email.strip().lower()
    if database.query(User).filter(User.email == email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email is already registered")

    user = User(email=email, password_hash=hash_password(request.password))
    database.add(user)
    database.commit()
    database.refresh(user)
    return AuthResponse(access_token=create_access_token(user.id), user_id=user.id)


@app.post("/api/v1/auth/login", response_model=AuthResponse, tags=["auth"])
def login(request: LoginRequest, database: Session = Depends(get_db)) -> AuthResponse:
    """Authenticate a user and return its access token."""
    email = request.email.strip().lower()
    user = database.query(User).filter(User.email == email).one_or_none()
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthResponse(access_token=create_access_token(user.id), user_id=user.id)


@app.post("/api/v1/reviews", response_model=ReviewResponse, status_code=202, tags=["reviews"])
def create_review(
    request: ReviewRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewResponse:
    """Persist a review request and return its initial processing state.

    The authenticated user owns the project and its review data.
    """
    review_rate_limiter.check_and_record(current_user.id)
    project = (
        database.query(Project)
        .filter(Project.owner_id == current_user.id, Project.name == request.project_name)
        .one_or_none()
    )
    if project is None:
        project = Project(owner=current_user, name=request.project_name)
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
    database.add(UsageRecord(user=current_user, usage_type="review", units=1))
    database.commit()
    database.refresh(review)

    return ReviewResponse(
        review_id=str(review.id),
        status="queued",
        message=f"Review accepted for {len(request.files)} file(s).",
    )


@app.get("/api/v1/me/usage", response_model=UsageResponse, tags=["usage"])
def get_usage(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> UsageResponse:
    """Return the authenticated user's review usage for the current hour."""
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(hours=1)
    review_count = (
        database.query(UsageRecord)
        .filter(
            UsageRecord.user_id == current_user.id,
            UsageRecord.usage_type == "review",
            UsageRecord.created_at >= period_start,
        )
        .count()
    )
    return UsageResponse(
        review_count=review_count,
        period_start=period_start,
        period_end=period_end,
        limit=review_rate_limiter.max_requests,
    )


@app.get("/api/v1/projects", response_model=list[ProjectResponse], tags=["projects"])
def list_projects(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ProjectResponse]:
    """List projects belonging to the authenticated user."""
    cached = cache.get_json(project_cache_key(current_user.id))
    if cached is not None:
        return [ProjectResponse.model_validate(project) for project in cached]

    projects = [
        ProjectResponse(
            id=project.id,
            name=project.name,
            files=[ProjectFileResponse(id=file.id, path=file.path) for file in project.files],
        )
        for project in current_user.projects
    ]
    cache.set_json(
        project_cache_key(current_user.id),
        [project.model_dump() for project in projects],
    )
    return projects


@app.post("/api/v1/projects", response_model=ProjectResponse, status_code=201, tags=["projects"])
def create_project(
    request: ProjectCreateRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    """Create an empty project owned by the authenticated user."""
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name cannot be blank")
    existing_project = (
        database.query(Project)
        .filter(Project.owner_id == current_user.id, Project.name == name)
        .one_or_none()
    )
    if existing_project is not None:
        raise HTTPException(status_code=409, detail="Project name already exists")

    project = Project(owner=current_user, name=name)
    database.add(project)
    database.commit()
    database.refresh(project)
    cache.delete(project_cache_key(current_user.id))
    return ProjectResponse(id=project.id, name=project.name, files=[])


@app.patch("/api/v1/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
def update_project(
    project_id: int,
    request: ProjectUpdateRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    """Rename an owned project."""
    project = (
        database.query(Project)
        .filter(Project.id == project_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name cannot be blank")
    duplicate = (
        database.query(Project)
        .filter(
            Project.owner_id == current_user.id,
            Project.name == name,
            Project.id != project_id,
        )
        .one_or_none()
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Project name already exists")

    project.name = name
    database.commit()
    database.refresh(project)
    cache.delete(project_cache_key(current_user.id))
    return ProjectResponse(
        id=project.id,
        name=project.name,
        files=[ProjectFileResponse(id=file.id, path=file.path) for file in project.files],
    )


@app.delete("/api/v1/projects/{project_id}", status_code=204, tags=["projects"])
def delete_project(
    project_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete an owned project and its related files and reviews."""
    project = (
        database.query(Project)
        .filter(Project.id == project_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    database.delete(project)
    database.commit()
    cache.delete(project_cache_key(current_user.id))
    return Response(status_code=204)


def _get_owned_project(project_id: int, current_user: User, database: Session) -> Project:
    project = (
        database.query(Project)
        .filter(Project.id == project_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _to_file_response(project_file: ProjectFile) -> FileResponse:
    return FileResponse(
        id=project_file.id,
        project_id=project_file.project_id,
        path=project_file.path,
        content=project_file.content,
    )


@app.post(
    "/api/v1/projects/{project_id}/files",
    response_model=FileResponse,
    status_code=201,
    tags=["files"],
)
def create_file(
    project_id: int,
    request: FileCreateRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Add one source file to an owned project."""
    project = _get_owned_project(project_id, current_user, database)
    path = request.path.strip()
    if not path:
        raise HTTPException(status_code=422, detail="File path cannot be blank")

    existing_file = (
        database.query(ProjectFile)
        .filter(ProjectFile.project_id == project.id, ProjectFile.path == path)
        .one_or_none()
    )
    if existing_file is not None:
        raise HTTPException(status_code=409, detail="File path already exists")

    project_file = ProjectFile(project=project, path=path, content=request.content)
    database.add(project_file)
    database.commit()
    database.refresh(project_file)
    cache.delete(project_cache_key(current_user.id))
    return _to_file_response(project_file)


@app.get(
    "/api/v1/projects/{project_id}/files",
    response_model=list[FileResponse],
    tags=["files"],
)
def list_files(
    project_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FileResponse]:
    """List files belonging to an owned project."""
    project = _get_owned_project(project_id, current_user, database)
    return [_to_file_response(project_file) for project_file in project.files]


@app.get("/api/v1/files/{file_id}", response_model=FileResponse, tags=["files"])
def get_file(
    file_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Read one file only when its project belongs to the current user."""
    project_file = (
        database.query(ProjectFile)
        .join(Project)
        .filter(ProjectFile.id == file_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if project_file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return _to_file_response(project_file)


@app.put("/api/v1/files/{file_id}", response_model=FileResponse, tags=["files"])
def update_file(
    file_id: int,
    request: FileUpdateRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Replace the content of an owned file."""
    project_file = (
        database.query(ProjectFile)
        .join(Project)
        .filter(ProjectFile.id == file_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if project_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    project_file.content = request.content
    database.commit()
    database.refresh(project_file)
    return _to_file_response(project_file)


@app.delete("/api/v1/files/{file_id}", status_code=204, tags=["files"])
def delete_file(
    file_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete an owned source file."""
    project_file = (
        database.query(ProjectFile)
        .join(Project)
        .filter(ProjectFile.id == file_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if project_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    database.delete(project_file)
    database.commit()
    cache.delete(project_cache_key(current_user.id))
    return Response(status_code=204)


@app.get("/api/v1/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
def get_project(
    project_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    """Return one project and its file paths."""
    project = (
        database.query(Project)
        .filter(Project.id == project_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
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
    project_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReviewSummaryResponse]:
    """List review runs for one project."""
    project = (
        database.query(Project)
        .filter(Project.id == project_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
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
def get_review(
    review_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewDetailResponse:
    """Return one review and its structured findings."""
    review = (
        database.query(Review)
        .join(Project)
        .filter(Review.id == review_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
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


def _get_owned_review(review_id: int, current_user: User, database: Session) -> Review:
    review = (
        database.query(Review)
        .join(Project)
        .filter(Review.id == review_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@app.patch(
    "/api/v1/reviews/{review_id}/status",
    response_model=ReviewSummaryResponse,
    tags=["reviews"],
)
def update_review_status(
    review_id: int,
    request: ReviewStatusUpdateRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewSummaryResponse:
    """Move a review through its processing lifecycle."""
    review = _get_owned_review(review_id, current_user, database)
    allowed_transitions = {
        "queued": {"processing", "failed"},
        "processing": {"completed", "failed"},
        "completed": set(),
        "failed": set(),
    }
    if request.status != review.status and request.status not in allowed_transitions[review.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move review from {review.status} to {request.status}",
        )

    review.status = request.status
    if request.summary is not None:
        review.summary = request.summary
    database.commit()
    database.refresh(review)
    return ReviewSummaryResponse(
        id=review.id,
        project_id=review.project_id,
        status=review.status,
        summary=review.summary,
    )


@app.post(
    "/api/v1/reviews/{review_id}/findings",
    response_model=ReviewFindingResponse,
    status_code=201,
    tags=["reviews"],
)
def create_finding(
    review_id: int,
    request: FindingCreateRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewFindingResponse:
    """Add one structured finding to an owned review."""
    review = _get_owned_review(review_id, current_user, database)
    if review.status not in {"queued", "processing"}:
        raise HTTPException(
            status_code=409,
            detail="Findings can only be added while a review is active",
        )

    finding = ReviewFinding(
        review=review,
        severity=request.severity.lower(),
        file_path=request.file_path.strip(),
        line_number=request.line_number,
        title=request.title.strip(),
        explanation=request.explanation,
        recommendation=request.recommendation,
    )
    database.add(finding)
    database.commit()
    database.refresh(finding)
    return ReviewFindingResponse(
        id=finding.id,
        severity=finding.severity,
        file_path=finding.file_path,
        line_number=finding.line_number,
        title=finding.title,
        explanation=finding.explanation,
        recommendation=finding.recommendation,
    )


@app.post(
    "/api/v1/reviews/{review_id}/run",
    response_model=ReviewDetailResponse,
    tags=["reviews"],
)
def run_review(
    review_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewDetailResponse:
    """Run the local Ollama reviewer and persist its findings."""
    review = _get_owned_review(review_id, current_user, database)
    if review.status != "queued":
        raise HTTPException(status_code=409, detail="Only queued reviews can be run")

    review.status = "processing"
    database.commit()
    files = [(project_file.path, project_file.content) for project_file in review.project.files]

    try:
        result = review_service.review(review.project.name, files)
        for finding in result.findings:
            review.findings.append(
                ReviewFinding(
                    severity=finding.severity,
                    file_path=finding.file_path,
                    line_number=finding.line_number,
                    title=finding.title,
                    explanation=finding.explanation,
                    recommendation=finding.recommendation,
                )
            )
        review.summary = result.summary
        review.status = "completed"
        database.commit()
        database.refresh(review)
    except AIReviewError as error:
        review.status = "failed"
        review.summary = str(error)
        database.commit()
        raise HTTPException(status_code=502, detail="The local AI reviewer failed") from error

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


@app.get("/api/v1/reviews/{review_id}/stream", tags=["reviews"])
def stream_review(
    review_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream review progress and Ollama output as server-sent events."""
    review = _get_owned_review(review_id, current_user, database)
    if review.status != "queued":
        raise HTTPException(status_code=409, detail="Only queued reviews can be streamed")

    review.status = "processing"
    database.commit()

    def events():
        yield f"data: {json.dumps({'type': 'status', 'status': 'processing'})}\n\n"
        content_parts: list[str] = []
        try:
            files = [
                (project_file.path, project_file.content)
                for project_file in review.project.files
            ]
            for chunk in review_service.stream_review(review.project.name, files):
                content_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            result = review_service.parse_result("".join(content_parts))
            for finding in result.findings:
                review.findings.append(
                    ReviewFinding(
                        severity=finding.severity,
                        file_path=finding.file_path,
                        line_number=finding.line_number,
                        title=finding.title,
                        explanation=finding.explanation,
                        recommendation=finding.recommendation,
                    )
                )
            review.summary = result.summary
            review.status = "completed"
            database.commit()
            yield f"data: {json.dumps({'type': 'status', 'status': 'completed'})}\n\n"
        except AIReviewError:
            review.status = "failed"
            database.commit()
            error_event = {"type": "error", "message": "The local AI reviewer failed"}
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "web", html=True), name="web")
