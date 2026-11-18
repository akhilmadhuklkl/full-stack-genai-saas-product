import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_FILES = 100
MAX_FILE_BYTES = 100_000
MAX_TOTAL_EXTRACTED_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    content: str


class ArchiveSecurityError(ValueError):
    """Raised when an archive exceeds a safety limit."""


def extract_safe_text_files(archive_bytes: bytes) -> tuple[list[ArchiveEntry], int]:
    """Extract safe relative UTF-8 files and return entries plus skipped count."""
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ArchiveSecurityError("Archive is larger than 5 MB")
    try:
        zip_file = zipfile.ZipFile(BytesIO(archive_bytes))
    except zipfile.BadZipFile as error:
        raise ArchiveSecurityError("Uploaded file is not a valid ZIP archive") from error

    members = [member for member in zip_file.infolist() if not member.is_dir()]
    if len(members) > MAX_ARCHIVE_FILES:
        raise ArchiveSecurityError("Archive contains more than 100 files")
    if sum(member.file_size for member in members) > MAX_TOTAL_EXTRACTED_BYTES:
        raise ArchiveSecurityError("Archive expands beyond the 20 MB extracted limit")

    entries: list[ArchiveEntry] = []
    skipped_files = 0
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts:
            skipped_files += 1
            continue
        try:
            content = zip_file.read(member).decode("utf-8")
        except (UnicodeDecodeError, ValueError, zipfile.BadZipFile):
            skipped_files += 1
            continue
        if not content or len(content) > MAX_FILE_BYTES:
            skipped_files += 1
            continue
        entries.append(ArchiveEntry(path=path.as_posix(), content=content))
    return entries, skipped_files
