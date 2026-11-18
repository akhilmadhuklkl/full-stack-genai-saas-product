import hashlib
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.ollama import AIReviewError, OllamaReviewService
from app.archive import ArchiveSecurityError, extract_safe_text_files
from app.cache import cache
from app.config import settings
from app.db.models import (
    EmailToken,
    Project,
    ProjectFile,
    Review,
    ReviewFinding,
    ReviewJob,
    RevokedToken,
    UsageRecord,
    User,
)
from app.db.session import SessionLocal, create_tables, engine, get_db
from app.dependencies import get_current_user
from app.email import EmailDeliveryError, send_email
from app.limits import login_attempt_limiter, review_rate_limiter
from app.observability import (
    CSRFMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    unhandled_error_handler,
    validation_error_handler,
)
from app.queue import enqueue_review, get_queue_health, get_worker_health
from app.schemas.account import AccountResponse, PasswordChangeRequest
from app.schemas.archive import ArchiveUploadResponse
from app.schemas.auth import (
    AuthResponse,
    EmailRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    RefreshRequest,
    RegisterRequest,
    TokenRequest,
)
from app.schemas.file import FileCreateRequest, FileResponse, FileUpdateRequest
from app.schemas.health import HealthComponent, HealthResponse
from app.schemas.job import JobResponse
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
from app.schemas.stats import FindingStatsResponse, ProjectStatsResponse, ReviewStatsResponse
from app.schemas.usage import UsageResponse
from app.schemas.version import VersionResponse
from app.security import (
    create_access_token,
    create_refresh_token,
    get_token_claims,
    hash_password,
    token_hash,
    verify_password,
)
from app.time import utcnow

logger = logging.getLogger("forge_review")
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
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a small readiness signal for local development and future deployment."""
    return {"status": "ok"}


@app.get("/metrics", tags=["system"])
def metrics() -> PlainTextResponse:
    """Expose low-cardinality operational metrics for future monitoring."""
    now = utcnow()
    stale_cutoff = now - timedelta(seconds=settings.job_stale_seconds)
    with SessionLocal() as database:
        review_counts = dict(
            database.query(Review.status, func.count(Review.id))
            .group_by(Review.status)
            .all()
        )
        queued_jobs = (
            database.query(ReviewJob).filter(ReviewJob.status == "queued").count()
        )
        processing_jobs = (
            database.query(ReviewJob).filter(ReviewJob.status == "processing").count()
        )
        stale_jobs = (
            database.query(ReviewJob)
            .filter(
                ReviewJob.status == "processing",
                ReviewJob.heartbeat_at < stale_cutoff,
            )
            .count()
        )
    queue_status, _ = get_queue_health()
    lines = [
        "# HELP forge_reviews_total Reviews grouped by lifecycle status.",
        "# TYPE forge_reviews_total gauge",
    ]
    for status_name in ("queued", "processing", "completed", "failed"):
        count = review_counts.get(status_name, 0)
        lines.append(f'forge_reviews_total{{status="{status_name}"}} {count}')
    lines.extend(
        [
            "# HELP forge_review_jobs Job queue and stale-job counts.",
            "# TYPE forge_review_jobs gauge",
            f'forge_review_jobs{{status="queued"}} {queued_jobs}',
            f'forge_review_jobs{{status="processing"}} {processing_jobs}',
            f'forge_review_jobs{{status="stale"}} {stale_jobs}',
            f'forge_queue_available {1 if queue_status == "ok" else 0}',
        ]
    )
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/api/v1/version", response_model=VersionResponse, tags=["system"])
def version_info() -> VersionResponse:
    """Return application and active prompt versions."""
    from app.version import __version__

    return VersionResponse(
        name="forge-review",
        version=__version__,
        prompt_version=settings.prompt_version,
    )


@app.get("/health/details", response_model=HealthResponse, tags=["system"])
def detailed_health_check() -> HealthResponse:
    """Check local dependencies without exposing credentials or connection strings."""
    components: dict[str, HealthComponent] = {}
    try:
        with engine.connect():
            components["database"] = HealthComponent(status="ok", detail="Database reachable")
    except SQLAlchemyError:
        components["database"] = HealthComponent(
            status="unavailable", detail="Database connection failed"
        )

    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=1.0)
        response.raise_for_status()
        components["ollama"] = HealthComponent(status="ok", detail="Ollama reachable")
    except httpx.HTTPError:
        components["ollama"] = HealthComponent(
            status="unavailable", detail="Ollama is not reachable"
        )

    queue_status, queue_detail = get_queue_health()
    components["redis"] = HealthComponent(status=queue_status, detail=queue_detail)
    if settings.email_provider == "resend" and settings.resend_api_key:
        components["email"] = HealthComponent(
            status="ok", detail="Resend email delivery configured"
        )
    elif settings.email_provider == "console" and settings.app_env != "production":
        components["email"] = HealthComponent(
            status="degraded", detail="Using local console email adapter"
        )
    else:
        components["email"] = HealthComponent(
            status="unavailable", detail="Email delivery is not configured"
        )
    worker_status, worker_detail = get_worker_health()
    try:
        stale_cutoff = utcnow() - timedelta(seconds=settings.job_stale_seconds)
        with SessionLocal() as database:
            stale_jobs = (
                database.query(ReviewJob)
                .filter(
                    ReviewJob.status == "processing",
                    ReviewJob.heartbeat_at < stale_cutoff,
                )
                .count()
            )
        if stale_jobs:
            worker_status = "degraded"
            worker_detail = f"{stale_jobs} review job(s) have stale heartbeats"
    except SQLAlchemyError:
        worker_status = "degraded"
        worker_detail = "Could not inspect review job heartbeats"
    components["workers"] = HealthComponent(status=worker_status, detail=worker_detail)
    overall_status = (
        "ok" if all(item.status == "ok" for item in components.values()) else "degraded"
    )
    return HealthResponse(status=overall_status, components=components)


@app.post("/api/v1/auth/register", response_model=AuthResponse, status_code=201, tags=["auth"])
def register(
    request: RegisterRequest,
    response: Response,
    database: Session = Depends(get_db),
) -> AuthResponse:
    """Create a user account and return its access token."""
    email = request.email.strip().lower()
    if database.query(User).filter(User.email == email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email is already registered")

    user = User(email=email, password_hash=hash_password(request.password))
    database.add(user)
    database.commit()
    database.refresh(user)
    _send_email_token(database, user, "verify_email")
    auth_response = _auth_response(user.id)
    _set_access_cookie(response, auth_response.access_token)
    return auth_response


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _send_email_token(database: Session, user: User, purpose: str) -> None:
    raw_token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(hours=24 if purpose == "verify_email" else 1)
    database.query(EmailToken).filter(
        EmailToken.user_id == user.id,
        EmailToken.purpose == purpose,
        EmailToken.used_at.is_(None),
    ).update({EmailToken.used_at: utcnow()}, synchronize_session=False)
    database.add(
        EmailToken(
            user_id=user.id,
            token_hash=_token_digest(raw_token),
            purpose=purpose,
            expires_at=expires_at,
        )
    )
    database.commit()
    action = "verify-email" if purpose == "verify_email" else "reset-password"
    subject = (
        "Verify your Forge Review email"
        if purpose == "verify_email"
        else "Reset your Forge Review password"
    )
    try:
        send_email(
            user.email,
            subject,
            f"Complete this action: {settings.public_base_url}/auth/{action}?token={raw_token}",
        )
    except EmailDeliveryError:
        logger.exception("email_delivery_failed purpose=%s user_id=%s", purpose, user.id)


def _consume_email_token(database: Session, raw_token: str, purpose: str) -> EmailToken:
    token = (
        database.query(EmailToken)
        .filter(
            EmailToken.token_hash == _token_digest(raw_token),
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > utcnow(),
        )
        .one_or_none()
    )
    if token is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    token.used_at = utcnow()
    return token


@app.post("/api/v1/auth/verify-email/request", status_code=202, tags=["auth"])
def request_email_verification(
    request: EmailRequest, database: Session = Depends(get_db)
) -> dict[str, str]:
    user = database.query(User).filter(User.email == request.email.strip().lower()).one_or_none()
    if user is not None and not user.email_verified:
        _send_email_token(database, user, "verify_email")
    return {"message": "If the account exists, a verification email has been sent."}


@app.post("/api/v1/auth/verify-email/confirm", status_code=204, tags=["auth"])
def confirm_email_verification(
    request: TokenRequest, database: Session = Depends(get_db)
) -> Response:
    token = _consume_email_token(database, request.token, "verify_email")
    user = database.get(User, token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user.email_verified = True
    database.commit()
    return Response(status_code=204)


@app.post("/api/v1/auth/password-reset/request", status_code=202, tags=["auth"])
def request_password_reset(
    request: EmailRequest, database: Session = Depends(get_db)
) -> dict[str, str]:
    user = database.query(User).filter(User.email == request.email.strip().lower()).one_or_none()
    if user is not None:
        _send_email_token(database, user, "password_reset")
    return {"message": "If the account exists, a password reset email has been sent."}


@app.post("/api/v1/auth/password-reset/confirm", status_code=204, tags=["auth"])
def confirm_password_reset(
    request: PasswordResetConfirmRequest, database: Session = Depends(get_db)
) -> Response:
    token = _consume_email_token(database, request.token, "password_reset")
    user = database.get(User, token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user.password_hash = hash_password(request.password)
    database.commit()
    return Response(status_code=204)


@app.post("/api/v1/auth/login", response_model=AuthResponse, tags=["auth"])
def login(
    request: LoginRequest,
    response: Response,
    database: Session = Depends(get_db),
) -> AuthResponse:
    """Authenticate a user and return its access token."""
    email = request.email.strip().lower()
    login_attempt_limiter.check(email)
    user = database.query(User).filter(User.email == email).one_or_none()
    if user is None or not verify_password(request.password, user.password_hash):
        login_attempt_limiter.record_failure(email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    login_attempt_limiter.reset(email)
    auth_response = _auth_response(user.id)
    _set_access_cookie(response, auth_response.access_token)
    return auth_response


def _auth_response(user_id: int) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
        user_id=user_id,
    )


def _set_access_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key="forge_access_token",
        value=access_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.auth_token_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        key="forge_csrf_token",
        value=secrets.token_urlsafe(24),
        httponly=False,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.auth_token_ttl_seconds,
        path="/",
    )


def _purge_expired_revocations(database: Session) -> None:
    database.query(RevokedToken).filter(
        RevokedToken.expires_at <= utcnow()
    ).delete(synchronize_session=False)


@app.post("/api/v1/auth/refresh", response_model=AuthResponse, tags=["auth"])
def refresh_token(request: RefreshRequest, database: Session = Depends(get_db)) -> AuthResponse:
    _purge_expired_revocations(database)
    claims = get_token_claims(request.refresh_token, expected_type="refresh")
    revoked = (
        database.query(RevokedToken)
        .filter(RevokedToken.token_hash == token_hash(request.refresh_token))
        .first()
    )
    user = database.get(User, claims.user_id) if claims is not None and revoked is None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    database.add(
        RevokedToken(
            token_hash=token_hash(request.refresh_token),
            expires_at=datetime.utcfromtimestamp(claims.expires_at),
        )
    )
    database.commit()
    return _auth_response(user.id)


@app.post("/api/v1/auth/logout", status_code=204, tags=["auth"])
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    database: Session = Depends(get_db),
) -> Response:
    _purge_expired_revocations(database)
    claims = get_token_claims(credentials.credentials)
    if claims is not None:
        database.add(
            RevokedToken(
                token_hash=token_hash(credentials.credentials),
                expires_at=datetime.utcfromtimestamp(claims.expires_at),
            )
        )
        database.commit()
    response = Response(status_code=204)
    response.delete_cookie("forge_access_token", path="/")
    return response


@app.get("/api/v1/me", response_model=AccountResponse, tags=["account"])
def get_account(current_user: User = Depends(get_current_user)) -> AccountResponse:
    """Return basic information for the authenticated user."""
    return AccountResponse(
        id=current_user.id,
        email=current_user.email,
        email_verified=current_user.email_verified,
    )


@app.post("/api/v1/me/password", status_code=204, tags=["account"])
def change_password(
    request: PasswordChangeRequest,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Change the authenticated user's password."""
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if request.current_password == request.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    current_user.password_hash = hash_password(request.new_password)
    database.commit()
    return Response(status_code=204)


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

    review = Review(project=project, status="queued", prompt_version=settings.prompt_version)
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
    period_end = utcnow()
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


@app.post(
    "/api/v1/reviews/{review_id}/enqueue",
    response_model=JobResponse,
    status_code=202,
    tags=["jobs"],
)
def enqueue_review_job(
    review_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Queue a review and return immediately with its job status."""
    review = _get_owned_review(review_id, current_user, database)
    if review.status != "queued":
        raise HTTPException(status_code=409, detail="Only queued reviews can be enqueued")
    if database.query(ReviewJob).filter(ReviewJob.review_id == review.id).one_or_none():
        raise HTTPException(status_code=409, detail="Review already has a job")

    job = ReviewJob(review=review, status="queued")
    database.add(job)
    database.commit()
    database.refresh(job)
    enqueue_review(review.id)
    return JobResponse(
        id=job.id,
        review_id=job.review_id,
        status=job.status,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        completed_at=job.completed_at,
    )


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, tags=["jobs"])
def get_job(
    job_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Return the status of an owned review job."""
    job = (
        database.query(ReviewJob)
        .join(Review)
        .join(Project)
        .filter(ReviewJob.id == job_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        id=job.id,
        review_id=job.review_id,
        status=job.status,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        completed_at=job.completed_at,
    )


@app.post("/api/v1/reviews/{review_id}/retry", response_model=JobResponse, tags=["jobs"])
def retry_review(
    review_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Reset a failed review and enqueue it again."""
    review = _get_owned_review(review_id, current_user, database)
    job = database.query(ReviewJob).filter(ReviewJob.review_id == review.id).one_or_none()
    if job is None or review.status != "failed" or job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed reviews can be retried")

    review.status = "queued"
    job.status = "queued"
    job.attempt_count = 0
    job.error_message = None
    job.started_at = None
    job.heartbeat_at = None
    job.completed_at = None
    database.commit()
    database.refresh(job)
    enqueue_review(review.id)
    return JobResponse(
        id=job.id,
        review_id=job.review_id,
        status=job.status,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        completed_at=job.completed_at,
    )


@app.post("/api/v1/reviews/{review_id}/recover", response_model=JobResponse, tags=["jobs"])
def recover_stale_review(
    review_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Requeue an owned review only when its worker heartbeat is stale."""
    review = _get_owned_review(review_id, current_user, database)
    job = database.query(ReviewJob).filter(ReviewJob.review_id == review.id).one_or_none()
    stale_cutoff = utcnow() - timedelta(seconds=settings.job_stale_seconds)
    if (
        job is None
        or review.status != "processing"
        or job.status != "processing"
        or job.heartbeat_at is None
        or job.heartbeat_at >= stale_cutoff
    ):
        raise HTTPException(status_code=409, detail="Review does not have a stale processing job")

    review.status = "queued"
    job.status = "queued"
    job.error_message = "Recovered after stale worker heartbeat"
    job.completed_at = None
    database.commit()
    database.refresh(job)
    enqueue_review(review.id)
    return JobResponse(
        id=job.id,
        review_id=job.review_id,
        status=job.status,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        completed_at=job.completed_at,
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
            review_instructions=project.review_instructions,
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

    project = Project(
        owner=current_user,
        name=name,
        review_instructions=request.review_instructions,
    )
    database.add(project)
    database.commit()
    database.refresh(project)
    cache.delete(project_cache_key(current_user.id))
    return ProjectResponse(
        id=project.id,
        name=project.name,
        review_instructions=project.review_instructions,
        files=[],
    )


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
    project.review_instructions = request.review_instructions
    database.commit()
    database.refresh(project)
    cache.delete(project_cache_key(current_user.id))
    return ProjectResponse(
        id=project.id,
        name=project.name,
        review_instructions=project.review_instructions,
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
    if len(project.files) >= 1000:
        raise HTTPException(status_code=413, detail="Project cannot contain more than 1000 files")
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


@app.post(
    "/api/v1/projects/{project_id}/archive",
    response_model=ArchiveUploadResponse,
    status_code=201,
    tags=["files"],
)
async def upload_archive(
    project_id: int,
    archive: UploadFile = File(...),
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArchiveUploadResponse:
    """Import safe UTF-8 source files from a ZIP archive."""
    project = _get_owned_project(project_id, current_user, database)
    archive_bytes = await archive.read()
    try:
        entries, skipped_files = extract_safe_text_files(archive_bytes)
    except ArchiveSecurityError as error:
        status_code = (
            413
            if any(marker in str(error) for marker in ("larger", "more than", "expands"))
            else 400
        )
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    existing_paths = {project_file.path for project_file in project.files}
    new_paths = {entry.path for entry in entries if entry.path not in existing_paths}
    if len(project.files) + len(new_paths) > 1000:
        raise HTTPException(status_code=413, detail="Project cannot contain more than 1000 files")

    for entry in entries:
        existing_file = (
            database.query(ProjectFile)
            .filter(ProjectFile.project_id == project.id, ProjectFile.path == entry.path)
            .one_or_none()
        )
        if existing_file is None:
            project.files.append(ProjectFile(path=entry.path, content=entry.content))
        else:
            existing_file.content = entry.content

    database.commit()
    cache.delete(project_cache_key(current_user.id))
    return ArchiveUploadResponse(
        project_id=project.id,
        imported_files=len(entries),
        skipped_files=skipped_files,
    )


@app.get(
    "/api/v1/projects/{project_id}/files",
    response_model=list[FileResponse],
    tags=["files"],
)
def list_files(
    project_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: str | None = None,
) -> list[FileResponse]:
    """List files belonging to an owned project."""
    project = _get_owned_project(project_id, current_user, database)
    files = project.files
    if search:
        search_term = search.lower()
        files = [project_file for project_file in files if search_term in project_file.path.lower()]
    return [_to_file_response(project_file) for project_file in files]


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
        review_instructions=project.review_instructions,
        files=[ProjectFileResponse(id=file.id, path=file.path) for file in project.files],
    )


@app.get(
    "/api/v1/projects/{project_id}/stats",
    response_model=ProjectStatsResponse,
    tags=["projects"],
)
def get_project_stats(
    project_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectStatsResponse:
    """Return review and finding counts for an owned project."""
    project = _get_owned_project(project_id, current_user, database)
    review_counts = {
        status_name: count
        for status_name, count in database.query(Review.status, func.count(Review.id))
        .filter(Review.project_id == project.id)
        .group_by(Review.status)
        .all()
    }
    severity_counts = {
        severity: count
        for severity, count in database.query(ReviewFinding.severity, func.count(ReviewFinding.id))
        .join(Review)
        .filter(Review.project_id == project.id)
        .group_by(ReviewFinding.severity)
        .all()
    }
    return ProjectStatsResponse(
        project_id=project.id,
        file_count=len(project.files),
        reviews=ReviewStatsResponse(
            total=sum(review_counts.values()),
            completed=review_counts.get("completed", 0),
            queued=review_counts.get("queued", 0) + review_counts.get("processing", 0),
            failed=review_counts.get("failed", 0),
        ),
        findings=FindingStatsResponse(
            low=severity_counts.get("low", 0),
            medium=severity_counts.get("medium", 0),
            high=severity_counts.get("high", 0),
            critical=severity_counts.get("critical", 0),
        ),
    )


@app.get(
    "/api/v1/projects/{project_id}/reviews",
    response_model=list[ReviewSummaryResponse],
    tags=["reviews"],
)
def list_reviews(
    response: Response,
    project_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    review_status: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
) -> list[ReviewSummaryResponse]:
    """List review runs for one project."""
    project = (
        database.query(Project)
        .filter(Project.id == project_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    query = database.query(Review).filter(Review.project_id == project.id)
    if review_status:
        query = query.filter(Review.status == review_status)
    if search:
        query = query.filter(Review.summary.ilike(f"%{search.strip()}%"))
    total = query.count()
    reviews = (
        query.order_by(Review.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    response.headers["X-Total-Count"] = str(total)
    jobs = {
        job.review_id: job
        for job in database.query(ReviewJob)
        .filter(ReviewJob.review_id.in_([review.id for review in reviews]))
        .all()
    }
    return [
        ReviewSummaryResponse(
            id=review.id,
            project_id=review.project_id,
            status=review.status,
            summary=review.summary,
            prompt_version=review.prompt_version,
            job_status=jobs[review.id].status if review.id in jobs else None,
            attempt_count=jobs[review.id].attempt_count if review.id in jobs else None,
            started_at=jobs[review.id].started_at if review.id in jobs else None,
            heartbeat_at=jobs[review.id].heartbeat_at if review.id in jobs else None,
            completed_at=jobs[review.id].completed_at if review.id in jobs else None,
        )
        for review in reviews
    ]


@app.get("/api/v1/reviews/{review_id}/export", tags=["reviews"])
def export_review(
    review_id: int,
    export_format: str = Query(default="json", alias="format"),
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download an owned review as JSON or Markdown."""
    review = (
        database.query(Review)
        .join(Project)
        .filter(Review.id == review_id, Project.owner_id == current_user.id)
        .one_or_none()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if export_format not in {"json", "markdown"}:
        raise HTTPException(status_code=400, detail="Format must be json or markdown")

    findings = [
        {
            "severity": finding.severity,
            "file_path": finding.file_path,
            "line_number": finding.line_number,
            "title": finding.title,
            "explanation": finding.explanation,
            "recommendation": finding.recommendation,
        }
        for finding in review.findings
    ]
    if export_format == "json":
        payload = {
            "review_id": review.id,
            "project_id": review.project_id,
            "status": review.status,
            "prompt_version": review.prompt_version,
            "summary": review.summary,
            "findings": findings,
        }
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="review-{review.id}.json"'},
        )

    lines = [
        f"# Forge Review #{review.id}",
        "",
        f"- **Status:** {review.status}",
        f"- **Prompt version:** {review.prompt_version}",
        "",
        "## Summary",
        "",
        review.summary or "No summary was generated.",
        "",
        "## Findings",
        "",
    ]
    for finding in findings:
        location = (
            f"{finding['file_path']}:{finding['line_number']}"
            if finding["line_number"]
            else finding["file_path"]
        )
        lines.extend(
            [
                f"### [{finding['severity'].upper()}] {finding['title']}",
                f"**Location:** `{location}`",
                "",
                finding["explanation"],
                "",
                f"**Recommendation:** {finding['recommendation']}",
                "",
            ]
        )
    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="review-{review.id}.md"'},
    )


@app.get("/api/v1/reviews/{review_id}", response_model=ReviewDetailResponse, tags=["reviews"])
def get_review(
    review_id: int,
    database: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    severity: str | None = None,
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

    findings = review.findings
    if severity:
        findings = [finding for finding in findings if finding.severity == severity.lower()]
    return ReviewDetailResponse(
        id=review.id,
        project_id=review.project_id,
        status=review.status,
        summary=review.summary,
        prompt_version=review.prompt_version,
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
            for finding in findings
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
        prompt_version=review.prompt_version,
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
        result = review_service.review(
            review.project.name,
            files,
            review.prompt_version,
            review.project.review_instructions,
        )
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
        prompt_version=review.prompt_version,
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
            for chunk in review_service.stream_review(
                review.project.name,
                files,
                review.prompt_version,
                review.project.review_instructions,
            ):
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
