from pydantic import BaseModel, Field


class FileCreateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)


class FileUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class FileResponse(BaseModel):
    id: int
    project_id: int
    path: str
    content: str
