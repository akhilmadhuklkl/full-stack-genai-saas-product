from typing import Literal

from pydantic import BaseModel, Field


class ReviewFile(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)


class ReviewRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=100)
    files: list[ReviewFile] = Field(min_length=1, max_length=20)


class ReviewResponse(BaseModel):
    review_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    message: str
