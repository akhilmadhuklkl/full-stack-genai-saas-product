from pydantic import BaseModel


class ReviewStatsResponse(BaseModel):
    total: int
    completed: int
    queued: int
    failed: int


class FindingStatsResponse(BaseModel):
    low: int
    medium: int
    high: int
    critical: int


class ProjectStatsResponse(BaseModel):
    project_id: int
    file_count: int
    reviews: ReviewStatsResponse
    findings: FindingStatsResponse
