from fastapi import FastAPI

from app.schemas.review import ReviewRequest, ReviewResponse

app = FastAPI(
    title="GenAI Code Review Assistant API",
    version="0.1.0",
    description="Backend foundation for the AI-powered code review SaaS product.",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a small readiness signal for local development and future deployment."""
    return {"status": "ok"}


@app.post("/api/v1/reviews", response_model=ReviewResponse, status_code=202, tags=["reviews"])
def create_review(request: ReviewRequest) -> ReviewResponse:
    """Accept a review request and return its initial processing state.

    AI execution will be added in a later milestone. Establishing this contract first
    lets the frontend and backend evolve against a stable request shape.
    """
    return ReviewResponse(
        review_id="review-local-placeholder",
        status="queued",
        message=f"Review accepted for {len(request.files)} file(s).",
    )
