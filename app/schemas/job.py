from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: int
    review_id: int
    status: Literal["queued", "processing", "completed", "failed"]
    attempt_count: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    completed_at: datetime | None
