# pyright: basic, reportMissingImports=false
"""Safe, bounded material-file staging primitives."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

DEFAULT_CHUNK_SIZE = 64 * 1024
_MAX_FILENAME_LENGTH = 255
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class UploadError(ValueError):
    """Base class for upload input errors that must not leave staged files."""


class UploadTooLargeError(UploadError):
    """The received stream exceeded the configured maximum byte size."""


class MalformedUploadError(UploadError):
    """The upload source did not provide a binary stream."""


@dataclass(frozen=True)
class StagedUpload:
    """A complete upload held in the upload root's temporary directory."""

    temp_path: Path
    byte_size: int
    sha256: str


def sanitize_display_filename(filename: str | None) -> str:
    """Keep a safe display name without allowing it to influence storage paths."""
    if not isinstance(filename, str):
        raise MalformedUploadError("filename must be text")
    normalized = unicodedata.normalize("NFKC", filename).replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    basename = _CONTROL_CHARS.sub("", basename).strip()
    if basename in {"", ".", ".."}:
        return "unnamed"
    # The database column is bounded and attachment names should not be enormous.
    return basename[:_MAX_FILENAME_LENGTH]


def material_storage_key(class_id: uuid.UUID, material_id: uuid.UUID) -> str:
    """Generate a storage key from server-owned identifiers only."""
    return f"{class_id}/{material_id}"


def contained_storage_path(upload_root: Path, storage_key: str) -> Path:
    """Resolve a generated/loaded key and reject paths outside the upload root."""
    root = upload_root.resolve()
    candidate = (root / storage_key).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("storage path escapes upload root")
    return candidate


def _temporary_path(upload_root: Path) -> Path:
    root = upload_root.resolve()
    temporary_root = root / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    resolved_temporary_root = temporary_root.resolve()
    if not resolved_temporary_root.is_relative_to(root):
        raise ValueError("temporary storage escapes upload root")
    # open(..., O_EXCL) in stage_upload provides the final collision check.
    return resolved_temporary_root / f"{uuid.uuid4().hex}.upload"


def verify_stored_file(
    path: Path,
    expected_size: int,
    expected_sha256: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> bool:
    """Verify a stored file completely before a successful download response."""
    if expected_size < 0 or chunk_size <= 0:
        return False
    try:
        if not path.is_file() or path.stat().st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(chunk_size):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256


def stage_upload(
    source: BinaryIO,
    upload_root: Path,
    max_bytes: int,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> StagedUpload:
    """Copy a binary upload to same-volume temporary storage while hashing it.

    The source is consumed in bounded chunks. Any malformed read, size violation,
    or filesystem failure removes the temporary file before the exception escapes.
    Empty files are valid at this layer; required-field and business validation are
    handled by the API/application layer.
    """
    if max_bytes < 0:
        raise ValueError("max_bytes must not be negative")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not hasattr(source, "read"):
        raise MalformedUploadError("upload file is not readable")

    temporary_path = _temporary_path(upload_root)
    file_descriptor: int | None = None
    total = 0
    digest = hashlib.sha256()
    try:
        file_descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(file_descriptor, "wb") as destination:
            file_descriptor = None
            while True:
                chunk = source.read(chunk_size)
                if not isinstance(chunk, bytes):
                    raise MalformedUploadError("upload stream returned non-bytes")
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadTooLargeError("upload exceeds configured maximum size")
                destination.write(chunk)
                digest.update(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        return StagedUpload(temporary_path, total, digest.hexdigest())
    except BaseException:
        if file_descriptor is not None:
            os.close(file_descriptor)
        temporary_path.unlink(missing_ok=True)
        raise


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MalformedUploadError",
    "StagedUpload",
    "UploadError",
    "UploadTooLargeError",
    "contained_storage_path",
    "material_storage_key",
    "sanitize_display_filename",
    "stage_upload",
    "verify_stored_file",
]
