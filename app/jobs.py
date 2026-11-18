import logging
from datetime import datetime

from app.ai.ollama import AIReviewError, OllamaReviewService
from app.db.models import Review, ReviewFinding, ReviewJob
from app.db.session import SessionLocal

logger = logging.getLogger("forge_review.jobs")


def process_review(review_id: int) -> None:
    review_service = OllamaReviewService()
    database = SessionLocal()
    job = database.query(ReviewJob).filter(ReviewJob.review_id == review_id).one_or_none()
    review = database.get(Review, review_id)
    if job is None or review is None:
        database.close()
        logger.error("job_missing review_id=%s", review_id)
        return

    try:
        now = datetime.utcnow()
        job.attempt_count += 1
        job.status = "processing"
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        review.status = "processing"
        database.commit()
        files = [(project_file.path, project_file.content) for project_file in review.project.files]
        result = review_service.review(
            review.project.name,
            files,
            review.prompt_version,
            review.project.review_instructions,
        )
        job.heartbeat_at = datetime.utcnow()
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
        job.status = "completed"
        job.heartbeat_at = datetime.utcnow()
        job.completed_at = datetime.utcnow()
        database.commit()
    except AIReviewError as error:
        review.status = "failed"
        job.status = "failed"
        job.error_message = str(error)
        job.completed_at = datetime.utcnow()
        database.commit()
        raise
    except Exception:
        logger.exception("job_failed review_id=%s", review_id)
        review.status = "failed"
        job.status = "failed"
        job.error_message = "Unexpected review worker failure"
        job.completed_at = datetime.utcnow()
        database.commit()
        raise
    finally:
        database.close()
