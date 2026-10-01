from pathlib import Path

import pytest
from pydantic import SecretStr
from pypdf import PdfWriter

from campusclaw.application.extraction import (
    ExtractionError,
    UnsupportedFormatError,
    chunk_segments,
    extract_pdf,
    extract_text,
    select_parser,
)
from campusclaw.config import AppEnvironment, Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        APP_ENV=AppEnvironment.TEST,
        DATABASE_URL="postgresql+psycopg://test:test@db/test",
        JWT_SIGNING_KEY=SecretStr("x" * 32),
        UPLOAD_ROOT=tmp_path,
    )


def test_parser_uses_signature_and_rejects_spoofed_pdf() -> None:
    assert select_parser("application/octet-stream", "notes.txt", b"hello") == "text"
    assert select_parser("application/octet-stream", "notes.md", b"# title") == "markdown"
    assert select_parser("application/octet-stream", "doc.bin", b"%PDF-1.7") == "pdf"
    with pytest.raises(ExtractionError, match="invalid_pdf_signature"):
        select_parser("application/pdf", "doc.pdf", b"not a pdf")
    with pytest.raises(UnsupportedFormatError):
        select_parser("application/octet-stream", "image.png", b"\x89PNG")


def test_utf8_markdown_keeps_line_provenance_and_bom(tmp_path: Path) -> None:
    found = extract_text(
        b"\xef\xbb\xbf# Intro\r\nChinese\r\nEnglish",
        content_type="text/markdown",
        filename="lesson.md",
        settings=settings(tmp_path),
    )
    assert [segment.text for segment in found] == ["# Intro", "Chinese", "English"]
    assert found[1].line_start == 2
    assert found[1].section_label == "Intro"


def test_pdf_extraction_is_page_scoped_and_image_only_is_safe(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    data_path = tmp_path / "empty.pdf"
    with data_path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ExtractionError, match="no_extractable_text"):
        extract_pdf(data_path.read_bytes(), settings=settings(tmp_path))


def test_chunking_never_crosses_pages_or_line_ranges() -> None:
    from campusclaw.application.extraction import ExtractedSegment

    chunks = chunk_segments(
        [
            ExtractedSegment("a" * 8, page=1),
            ExtractedSegment("b" * 8, page=2),
        ],
        chunk_chars=10,
        overlap_chars=2,
        max_chunks=10,
    )
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert all(chunk.line_start is None for chunk in chunks)


def test_chunking_splits_a_single_long_text_line() -> None:
    from campusclaw.application.extraction import ExtractedSegment

    chunks = chunk_segments(
        [ExtractedSegment("课程内容 " + "细节 " * 100, line_start=7, line_end=7)],
        chunk_chars=40,
        overlap_chars=8,
        max_chunks=20,
    )
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 40 for chunk in chunks)
    assert all((chunk.line_start, chunk.line_end) == (7, 7) for chunk in chunks)
