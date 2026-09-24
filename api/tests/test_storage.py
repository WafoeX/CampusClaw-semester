# pyright: basic, reportMissingImports=false

import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from campusclaw.application.storage import (
    MalformedUploadError,
    UploadTooLargeError,
    contained_storage_path,
    material_storage_key,
    sanitize_display_filename,
    stage_upload,
)


def test_stage_upload_counts_bytes_and_hashes_in_bounded_chunks(tmp_path: Path) -> None:
    payload = b"campusclaw" * 10
    staged = stage_upload(BytesIO(payload), tmp_path, len(payload), chunk_size=3)

    assert staged.byte_size == len(payload)
    assert staged.sha256 == hashlib.sha256(payload).hexdigest()
    assert staged.temp_path.parent == tmp_path / "tmp"
    assert staged.temp_path.read_bytes() == payload


def test_empty_upload_is_staged_without_loading_a_whole_file(tmp_path: Path) -> None:
    staged = stage_upload(BytesIO(), tmp_path, 0)

    assert staged.byte_size == 0
    assert staged.sha256 == hashlib.sha256(b"").hexdigest()
    assert staged.temp_path.exists()


def test_oversized_upload_is_removed_at_the_boundary(tmp_path: Path) -> None:
    with pytest.raises(UploadTooLargeError):
        stage_upload(BytesIO(b"12345"), tmp_path, 4, chunk_size=2)

    assert list((tmp_path / "tmp").iterdir()) == []


def test_malformed_stream_is_removed(tmp_path: Path) -> None:
    class Malformed:
        def read(self, size: int) -> str:
            del size
            return "not bytes"

    with pytest.raises(MalformedUploadError):
        stage_upload(Malformed(), tmp_path, 10)  # type: ignore[arg-type]

    assert list((tmp_path / "tmp").iterdir()) == []


def test_filename_is_metadata_only_and_path_syntax_is_removed() -> None:
    assert sanitize_display_filename(r"..\..\secret.txt") == "secret.txt"
    assert sanitize_display_filename("/var/tmp/lesson.pdf") == "lesson.pdf"
    assert sanitize_display_filename("..") == "unnamed"
    assert sanitize_display_filename("\x00 lesson\n.txt ") == "lesson.txt"


def test_storage_key_is_generated_and_containment_is_enforced(tmp_path: Path) -> None:
    import uuid

    class_id = uuid.uuid4()
    material_id = uuid.uuid4()
    key = material_storage_key(class_id, material_id)
    assert contained_storage_path(tmp_path, key) == (tmp_path / key).resolve()

    with pytest.raises(ValueError):
        contained_storage_path(tmp_path, "../outside")
