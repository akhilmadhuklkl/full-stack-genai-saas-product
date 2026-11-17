import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.ai.ollama import AIReviewError, OllamaReviewService
from app.db.models import Review, ReviewFinding, ReviewJob
from app.db.session import SessionLocal

logger = logging.getLogger("forge_review.jobs")
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="review-worker")


def enqueue_review(review_id: int, review_service: OllamaReviewService) -> None:
    executor.submit(process_review, review_id, review_service)


def process_review(review_id: int, review_service: OllamaReviewService) -> None:
    database = SessionLocal()
    job = database.query(ReviewJob).filter(ReviewJob.review_id == review_id).one_or_none()
    review = database.get(Review, review_id)
    if job is None or review is None:
        database.close()
        logger.error("job_missing review_id=%s", review_id)
        return

    try:
        job.status = "processing"
        review.status = "processing"
        database.commit()
        files = [(project_file.path, project_file.content) for project_file in review.project.files]
        result = review_service.review(review.project.name, files, review.prompt_version)
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
        job.completed_at = datetime.utcnow()
        database.commit()
    except AIReviewError as error:
        review.status = "failed"
        job.status = "failed"
        job.error_message = str(error)
        job.completed_at = datetime.utcnow()
        database.commit()
    except Exception:
        logger.exception("job_failed review_id=%s", review_id)
        review.status = "failed"
        job.status = "failed"
        job.error_message = "Unexpected review worker failure"
        job.completed_at = datetime.utcnow()
        database.commit()
    finally:
        database.close()
