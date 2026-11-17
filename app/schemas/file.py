from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator


class FileCreateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value.strip())
        if not value.strip() or path.is_absolute() or ".." in path.parts:
            raise ValueError("File path must be a safe relative path")
        return path.as_posix()


class FileUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class FileResponse(BaseModel):
    id: int
    project_id: int
    path: str
    content: str
