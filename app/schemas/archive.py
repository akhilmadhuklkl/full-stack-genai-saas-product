from pydantic import BaseModel


class ArchiveUploadResponse(BaseModel):
    project_id: int
    imported_files: int
    skipped_files: int
