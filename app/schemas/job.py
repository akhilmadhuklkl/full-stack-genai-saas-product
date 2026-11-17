from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: int
    review_id: int
    status: Literal["queued", "processing", "completed", "failed"]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
