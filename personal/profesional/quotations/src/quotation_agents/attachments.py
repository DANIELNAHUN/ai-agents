"""Text extraction for quotation requirement documents."""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfReader


SUPPORTED_ATTACHMENT_SUFFIXES = {".docx", ".md", ".pdf", ".txt"}


class AttachmentError(ValueError):
    """Raised when an attachment cannot be read or has an unsupported format."""


@dataclass(frozen=True)
class SourceDocument:
    """Extracted text from one user-provided source document."""

    name: str
    text: str


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise AttachmentError(f"Could not read DOCX attachment: {path}") from exc
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in document.iter(f"{namespace}p"):
        value = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        if value.strip():
            paragraphs.append(value)
    return "\n".join(paragraphs)


def _read_pdf(path: Path) -> str:
    try:
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise AttachmentError(f"Could not read PDF attachment: {path}") from exc


def load_source_document(path: str | Path) -> SourceDocument:
    """Read one supported document and return its extracted text."""

    source = Path(path).expanduser()
    if not source.is_file():
        raise AttachmentError(f"Attachment does not exist or is not a file: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_ATTACHMENT_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_ATTACHMENT_SUFFIXES))
        raise AttachmentError(f"Unsupported attachment type {suffix!r}: {source}; use {supported}")

    try:
        if suffix in {".txt", ".md"}:
            content = source.read_text(encoding="utf-8-sig")
        elif suffix == ".docx":
            content = _read_docx(source)
        else:
            content = _read_pdf(source)
    except UnicodeError as exc:
        raise AttachmentError(f"Attachment must use UTF-8 text encoding: {source}") from exc

    if not content.strip():
        raise AttachmentError(
            f"No text could be extracted from {source}; scanned PDFs need OCR first"
        )
    return SourceDocument(name=source.name, text=content.strip())


def load_source_documents(paths: Sequence[str | Path]) -> tuple[SourceDocument, ...]:
    """Load a sequence of quotation requirement documents."""

    return tuple(load_source_document(path) for path in paths)


def format_source_documents(documents: Sequence[SourceDocument]) -> str:
    """Format extracted documents as clearly delimited source data."""

    return "\n".join(
        f"<source_document name={document.name!r}>\n{document.text}\n</source_document>"
        for document in documents
    )
