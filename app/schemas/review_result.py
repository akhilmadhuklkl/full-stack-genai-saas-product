from typing import Literal

from pydantic import BaseModel, Field

ReviewStatus = Literal["queued", "processing", "completed", "failed"]


class ReviewStatusUpdateRequest(BaseModel):
    status: ReviewStatus
    summary: str | None = Field(default=None, max_length=50_000)


class FindingCreateRequest(BaseModel):
    severity: str = Field(min_length=1, max_length=20)
    file_path: str = Field(min_length=1, max_length=500)
    line_number: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=50_000)
    recommendation: str = Field(min_length=1, max_length=50_000)
