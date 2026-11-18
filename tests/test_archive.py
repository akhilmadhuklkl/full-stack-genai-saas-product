import zipfile
from io import BytesIO

import pytest

from app.archive import ArchiveSecurityError, extract_safe_text_files


def make_zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_archive_imports_utf8_files_and_skips_traversal() -> None:
    entries, skipped = extract_safe_text_files(
        make_zip({"src/app.py": b"print(1)", "../secret.txt": b"secret"})
    )

    assert [entry.path for entry in entries] == ["src/app.py"]
    assert skipped == 1


def test_archive_skips_binary_files() -> None:
    entries, skipped = extract_safe_text_files(make_zip({"image.bin": b"\xff\xfe"}))

    assert entries == []
    assert skipped == 1


def test_invalid_archive_is_rejected() -> None:
    with pytest.raises(ArchiveSecurityError, match="valid ZIP"):
        extract_safe_text_files(b"not-a-zip")


def test_archive_rejects_large_expanded_content() -> None:
    with pytest.raises(ArchiveSecurityError, match="20 MB extracted limit"):
        extract_safe_text_files(make_zip({"large.txt": b"x" * (20 * 1024 * 1024 + 1)}))
