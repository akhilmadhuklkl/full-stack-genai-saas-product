from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectFile, Review, User
from app.db.session import create_tables, get_db
from app.dependencies import get_current_user
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
from app.security import create_access_token, hash_password, verify_password


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
    database.commit()
    database.refresh(review)

    return ReviewResponse(
        review_id=str(review.id),
        status="queued",
        message=f"Review accepted for {len(request.files)} file(s).",
    )


@app.get("/api/v1/projects", response_model=list[ProjectResponse], tags=["projects"])
def list_projects(
    database: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ProjectResponse]:
    """List projects belonging to the authenticated user."""
    return [
        ProjectResponse(
            id=project.id,
            name=project.name,
            files=[ProjectFileResponse(id=file.id, path=file.path) for file in project.files],
        )
        for project in current_user.projects
    ]


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
