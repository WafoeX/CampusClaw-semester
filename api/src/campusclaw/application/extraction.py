"""Bounded PDF, UTF-8 text, and Markdown extraction with provenance."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from campusclaw.config import Settings

PDF_SIGNATURE = b"%PDF-"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}
TEXT_EXTENSIONS = {".txt", ".text", ".log", ".csv", ".json", ".yaml", ".yml"}
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")


class ExtractionError(ValueError):
    """Safe, stable extraction failure; the detail is never provider output."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class UnsupportedFormatError(ExtractionError):
    def __init__(self) -> None:
        super().__init__("unsupported_format")


@dataclass(frozen=True)
class ExtractedSegment:
    text: str
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_label: str | None = None


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_label: str | None = None


def _extension(filename: str) -> str:
    return Path(filename.replace("\\", "/")).suffix.casefold()


def select_parser(content_type: str, filename: str, signature: bytes) -> str:
    """Select from bounded signals; never trust a browser-provided MIME type alone."""
    content = content_type.casefold().split(";", 1)[0].strip()
    ext = _extension(filename)
    is_pdf = signature.startswith(PDF_SIGNATURE)
    if is_pdf:
        return "pdf"
    if content == "application/pdf" or ext == ".pdf":
        raise ExtractionError("invalid_pdf_signature")
    if content in {"text/plain", "text/markdown", "text/x-markdown"} or ext in (
        MARKDOWN_EXTENSIONS | TEXT_EXTENSIONS
    ):
        return (
            "markdown"
            if content in {"text/markdown", "text/x-markdown"} or ext in MARKDOWN_EXTENSIONS
            else "text"
        )
    raise UnsupportedFormatError()


def _bounded_utf8(data: bytes, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise ExtractionError("extraction_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionError("invalid_utf8") from exc
    if "\x00" in text:
        raise ExtractionError("binary_content")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _markdown_segments(text: str) -> list[ExtractedSegment]:
    lines = text.split("\n")
    sections: list[ExtractedSegment] = []
    current_section: str | None = None
    for number, line in enumerate(lines, start=1):
        heading = HEADING_RE.match(line)
        if heading:
            current_section = heading.group(1).strip()[:200] or None
        if line.strip():
            sections.append(
                ExtractedSegment(
                    text=line,
                    line_start=number,
                    line_end=number,
                    section_label=current_section,
                )
            )
    return sections


def extract_text(
    data: bytes, *, content_type: str, filename: str, settings: Settings
) -> list[ExtractedSegment]:
    parser = select_parser(content_type, filename, data[:8])
    if parser == "pdf":
        return extract_pdf(data, settings=settings)
    return _markdown_segments(_bounded_utf8(data, settings.EXTRACTION_MAX_BYTES))


def extract_pdf(data: bytes, *, settings: Settings) -> list[ExtractedSegment]:
    if len(data) > settings.EXTRACTION_MAX_BYTES:
        raise ExtractionError("extraction_too_large")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception as exc:  # pypdf has several parser-specific exception classes.
        raise ExtractionError("invalid_pdf") from exc
    segments: list[ExtractedSegment] = []
    total_chars = 0
    for page_number, page in enumerate(reader.pages, start=1):
        if page_number > settings.EXTRACTION_MAX_CHUNKS:
            raise ExtractionError("page_limit_exceeded")
        try:
            text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
        except Exception as exc:
            raise ExtractionError("pdf_text_extraction_failed") from exc
        text = text.strip()
        if not text:
            continue
        total_chars += len(text)
        if total_chars > settings.EXTRACTION_MAX_CHARS:
            raise ExtractionError("character_limit_exceeded")
        for paragraph in (part.strip() for part in text.split("\n\n")):
            if paragraph:
                segments.append(ExtractedSegment(text=paragraph, page=page_number))
    if not segments:
        raise ExtractionError("no_extractable_text")
    return segments


def _split_ranges(text: str, limit: int, overlap: int) -> list[tuple[int, int, str]]:
    if limit <= 0 or overlap >= limit:
        raise ValueError("invalid chunk bounds")
    pieces: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + limit)
        piece = text[start:end].strip()
        if piece:
            pieces.append((start, end, piece))
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return pieces


def _split_text(text: str, limit: int, overlap: int) -> list[str]:
    return [piece for _, _, piece in _split_ranges(text, limit, overlap)]


def chunk_segments(
    segments: list[ExtractedSegment],
    *,
    chunk_chars: int,
    overlap_chars: int,
    max_chunks: int,
) -> list[Chunk]:
    """Chunk only within one page or contiguous line range."""
    if len(segments) == 0:
        raise ExtractionError("no_extractable_text")
    if overlap_chars >= chunk_chars:
        raise ValueError("overlap must be smaller than chunk size")
    chunks: list[Chunk] = []
    groups: list[list[ExtractedSegment]] = []
    group_key: tuple[int | None, int | None] | None = None
    for segment in segments:
        key = (segment.page, None if segment.page is not None else segment.line_start)
        if group_key is None or (segment.page is not None and key[0] != group_key[0]):
            groups.append([])
            group_key = key
        groups[-1].append(segment)

    for group in groups:
        if not group:
            continue
        if group[0].page is not None:
            for text in _split_text(
                "\n".join(item.text for item in group), chunk_chars, overlap_chars
            ):
                chunks.append(Chunk(text=text, page=group[0].page))
        else:
            joined = "\n".join(item.text for item in group)
            offsets: list[tuple[int, int]] = []
            cursor = 0
            for item in group:
                end = cursor + len(item.text)
                offsets.append((cursor, end))
                cursor = end + 1
            for start, end, piece in _split_ranges(joined, chunk_chars, overlap_chars):
                covered = [
                    index
                    for index, (line_start, line_end) in enumerate(offsets)
                    if line_end > start and line_start < end
                ]
                if not covered:
                    continue
                first, last = covered[0], covered[-1]
                chunks.append(
                    Chunk(
                        text=piece,
                        line_start=group[first].line_start,
                        line_end=group[last].line_end,
                        section_label=group[first].section_label,
                    )
                )
        if len(chunks) > max_chunks:
            raise ExtractionError("chunk_limit_exceeded")
    return [chunk for chunk in chunks if chunk.text]
