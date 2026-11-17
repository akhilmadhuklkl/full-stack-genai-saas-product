from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
