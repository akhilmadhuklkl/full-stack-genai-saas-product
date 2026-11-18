from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    review_instructions: str | None = Field(default=None, max_length=5_000)


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    review_instructions: str | None = Field(default=None, max_length=5_000)
