from typing import Literal

from pydantic import BaseModel


class HealthComponent(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    components: dict[str, HealthComponent]
