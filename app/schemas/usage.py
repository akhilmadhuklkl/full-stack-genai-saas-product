from datetime import datetime

from pydantic import BaseModel


class UsageResponse(BaseModel):
    review_count: int
    period_start: datetime
    period_end: datetime
    limit: int
