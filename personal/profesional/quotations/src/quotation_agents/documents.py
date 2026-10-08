"""Deterministic DOCX proposal generation for approved quotation results."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal
from xml.etree import ElementTree as ET

from .models import QuotationDraft, QuotationTask, WorkCategory
from .pricing import QuoteResult, _draft_fingerprint
from .workflow import require_approved_draft

Language = Literal["en", "es"]
PdfConverter = Callable[[Path, Path], None]
PdfRunner = Callable[[Sequence[str]], object]

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_R = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("w", _W)
ET.register_namespace("", _CT)
ET.register_namespace("r", _R)


class ProposalDocumentError(ValueError):
    """Raised when a proposal cannot be generated or validated safely."""


@dataclass(frozen=True)
class DocumentValidation:
    """Structural validation metadata for one generated document."""

    format: Literal["docx", "pdf"]
    valid: bool
    size_bytes: int
    text_length: int | None = None
    parts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProposalDocuments:
    """Paths and validation metadata returned by proposal generation."""

    docx_path: Path
    pdf_path: Path | None
    docx_validation: DocumentValidation
    pdf_validation: DocumentValidation | None


_CATEGORY_LABELS = {
    "en": {
        WorkCategory.PLANNING_AND_COORDINATION: "Planning and coordination",
        WorkCategory.BACKEND: "Backend",
        WorkCategory.FRONTEND: "Frontend",
        WorkCategory.DEVOPS: "DevOps",
    },
    "es": {
        WorkCategory.PLANNING_AND_COORDINATION: "Planificación y coordinación",
        WorkCategory.BACKEND: "Backend",
        WorkCategory.FRONTEND: "Frontend",
        WorkCategory.DEVOPS: "DevOps",
    },
}

_TEXT = {
    "en": {
        "title": "Quotation Proposal",
        "client": "Client / company",
        "request": "Original request",
        "scope": "Interpreted scope",
        "tasks": "Tasks by category",
        "no_tasks": "No tasks recorded for this category.",
        "hours": "Hours",
        "days": "Calendar days (3 hours/day)",
        "effort": "Effort and category pricing",
        "category": "Category",
        "rate": "Rate (PEN/hour)",
        "subtotal": "Subtotal (PEN)",
        "summary": "Commercial amounts",
        "minimum": "Minimum",
        "ideal": "Ideal",
        "maximum": "Maximum",
        "selected": "Selected",
        "payment": "Payment schedule",
        "milestone": "Milestone / module",
        "amount": "Amount (PEN)",
        "percentage": "Share",
        "conditions": "Commercial conditions",
        "igv": "IGV is excluded.",
        "validity": "This quotation is valid for 14 calendar days.",
        "overage": (
            "The selected amount exceeds S/ 10,000. The overage is retained; "
            "modularization and manual approval are required."
        ),
        "assumptions": "Assumptions",
        "risks": "Risks",
        "questions": "Questions pending confirmation",
        "none": "None recorded.",
        "exclusions": "Separate-charge exclusions",
        "adjustments": "Adjustments to approved deliverables are charged separately.",
        "new_functionality": (
            "New functionality outside the approved requirements is charged separately."
        ),
        "migrations": "Server migrations are charged separately.",
    },
    "es": {
        "title": "Propuesta de cotización",
        "client": "Cliente / empresa",
        "request": "Solicitud original",
        "scope": "Alcance interpretado",
        "tasks": "Tareas por categoría",
        "no_tasks": "No hay tareas registradas para esta categoría.",
        "hours": "Horas",
        "days": "Días calendario (3 horas/día)",
        "effort": "Esfuerzo y precios por categoría",
        "category": "Categoría",
        "rate": "Tarifa (PEN/hora)",
        "subtotal": "Subtotal (PEN)",
        "summary": "Montos comerciales",
        "minimum": "Mínimo",
        "ideal": "Ideal",
        "maximum": "Máximo",
        "selected": "Seleccionado",
        "payment": "Cronograma de pagos",
        "milestone": "Hito / módulo",
        "amount": "Monto (PEN)",
        "percentage": "Participación",
        "conditions": "Condiciones comerciales",
        "igv": "El IGV no está incluido.",
        "validity": "Esta cotización tiene una vigencia de 14 días calendario.",
        "overage": (
            "El monto seleccionado supera S/ 10,000. El excedente se conserva; "
            "se requiere modularización y aprobación manual."
        ),
        "assumptions": "Supuestos",
        "risks": "Riesgos",
        "questions": "Preguntas pendientes de confirmación",
        "none": "No se registraron.",
        "exclusions": "Exclusiones con cobro separado",
        "adjustments": "Los ajustes a los entregables aprobados se cobran por separado.",
        "new_functionality": (
            "La funcionalidad nueva fuera de los requisitos aprobados se cobra por separado."
        ),
        "migrations": "Las migraciones de servidores se cobran por separado.",
    },
}


def _money(value: object) -> str:
    return f"S/ {value}"


def _language(language: Language) -> dict[str, str]:
    if language not in _TEXT:
        raise ProposalDocumentError("language must be 'en' or 'es'")
    return _TEXT[language]


def _paragraph(text: str = "", *, style: str | None = None, bold: bool = False) -> ET.Element:
    paragraph = ET.Element(f"{{{_W}}}p")
    if style:
        properties = ET.SubElement(paragraph, f"{{{_W}}}pPr")
        ET.SubElement(properties, f"{{{_W}}}pStyle", {f"{{{_W}}}val": style})
    run = ET.SubElement(paragraph, f"{{{_W}}}r")
    if bold:
        run_properties = ET.SubElement(run, f"{{{_W}}}rPr")
        ET.SubElement(run_properties, f"{{{_W}}}b")
    text_node = ET.SubElement(run, f"{{{_W}}}t")
    if text[:1].isspace() or text[-1:].isspace():
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text
    return paragraph


def _table(rows: Sequence[Sequence[str]]) -> ET.Element:
    table = ET.Element(f"{{{_W}}}tbl")
    properties = ET.SubElement(table, f"{{{_W}}}tblPr")
    ET.SubElement(properties, f"{{{_W}}}tblStyle", {f"{{{_W}}}val": "TableGrid"})
    for row_index, row in enumerate(rows):
        row_node = ET.SubElement(table, f"{{{_W}}}tr")
        for value in row:
            cell = ET.SubElement(row_node, f"{{{_W}}}tc")
            cell.append(_paragraph(value, bold=row_index == 0))
    return table


def _items(document: ET.Element, values: Sequence[str], text: dict[str, str]) -> None:
    if not values:
        document.append(_paragraph(text["none"]))
        return
    for value in values:
        document.append(_paragraph(f"- {value}"))


def _task_text(task: QuotationTask) -> str:
    hours = "" if task.estimated_hours is None else f" ({task.estimated_hours} hours)"
    return f"{task.description}{hours}"


def _proposal_xml(draft: QuotationDraft, quote: QuoteResult, language: Language) -> bytes:
    text = _language(language)
    labels = _CATEGORY_LABELS[language]
    document = ET.Element(f"{{{_W}}}document")
    body = ET.SubElement(document, f"{{{_W}}}body")
    body.append(_paragraph(text["title"], style="Title"))
    body.append(_paragraph(f"{text['client']}: {draft.client_company}"))
    body.append(_paragraph(text["request"], style="Heading1"))
    body.append(_paragraph(draft.original_request))
    body.append(_paragraph(text["scope"], style="Heading1"))
    _items(body, draft.inferred_scope, text)
    body.append(_paragraph(text["tasks"], style="Heading1"))
    for category in WorkCategory:
        body.append(_paragraph(labels[category], style="Heading2"))
        category_tasks = [task for task in draft.tasks if task.category is category]
        if not category_tasks:
            body.append(_paragraph(text["no_tasks"]))
        for task in category_tasks:
            body.append(_paragraph(_task_text(task)))

    body.append(_paragraph(text["effort"], style="Heading1"))
    body.append(_paragraph(f"{text['hours']}: {quote.effort.total_hours}"))
    body.append(_paragraph(f"{text['days']}: {quote.effort.calendar_days}"))
    category_rows = [[text["category"], text["hours"], text["rate"], text["subtotal"]]]
    for estimate in quote.effort.categories:
        category_rows.append(
            [
                labels[estimate.category],
                str(estimate.hours),
                _money(estimate.rate),
                _money(estimate.subtotal),
            ]
        )
    body.append(_table(category_rows))

    body.append(_paragraph(text["summary"], style="Heading1"))
    body.append(
        _table(
            [
                ["Band", "Amount (PEN)"],
                [text["minimum"], _money(quote.minimum_amount)],
                [text["ideal"], _money(quote.ideal_amount)],
                [text["maximum"], _money(quote.maximum_amount)],
                [text["selected"], _money(quote.selected_amount)],
            ]
        )
    )
    body.append(_paragraph(text["payment"], style="Heading1"))
    payment_rows = [[text["milestone"], text["amount"], text["percentage"]]]
    for payment in quote.payment_schedule.payments:
        share = "" if payment.percentage is None else f"{payment.percentage * 100}%"
        payment_rows.append([payment.label, _money(payment.amount), share])
    body.append(_table(payment_rows))

    body.append(_paragraph(text["conditions"], style="Heading1"))
    body.append(_paragraph(text["igv"]))
    body.append(_paragraph(text["validity"]))
    if quote.ceiling_exceeded:
        body.append(_paragraph(text["overage"]))

    for section in ("assumptions", "risks", "questions"):
        body.append(_paragraph(text[section], style="Heading1"))
        _items(body, getattr(draft, section), text)
    body.append(_paragraph(text["exclusions"], style="Heading1"))
    for key in ("adjustments", "new_functionality", "migrations"):
        body.append(_paragraph(text[key]))
    body.append(ET.Element(f"{{{_W}}}sectPr"))
    return ET.tostring(document, encoding="utf-8", xml_declaration=True)


def _docx_bytes(document_xml: bytes) -> bytes:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_CT}">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    ).encode()
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_R}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '</Relationships>'
    ).encode()
    document_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_R}"/>'
    ).encode()
    parts = (
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", relationships),
        ("word/document.xml", document_xml),
        ("word/_rels/document.xml.rels", document_relationships),
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            archive.writestr(info, content)
    return stream.getvalue()


def validate_docx(path: Path) -> DocumentValidation:
    """Validate the ZIP/XML structure and text body of a DOCX file."""

    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ProposalDocumentError("DOCX contains a corrupt ZIP member")
            names = tuple(archive.namelist())
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
            if not required.issubset(names):
                raise ProposalDocumentError("DOCX is missing required package parts")
            root = ET.fromstring(archive.read("word/document.xml"))
            body_text = "".join(root.itertext()).strip()
    except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ProposalDocumentError(f"invalid DOCX: {path}") from exc
    if not body_text:
        raise ProposalDocumentError("DOCX body must contain text")
    return DocumentValidation("docx", True, path.stat().st_size, len(body_text), names)


def validate_pdf(path: Path) -> DocumentValidation:
    """Perform dependency-free structural validation of a generated PDF."""

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProposalDocumentError(f"cannot read PDF: {path}") from exc
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise ProposalDocumentError("PDF must contain a header and EOF marker")
    return DocumentValidation("pdf", True, len(data))


def libreoffice_pdf_converter(
    docx_path: Path,
    pdf_path: Path,
    *,
    runner: PdfRunner | None = None,
) -> None:
    """Convert one DOCX using LibreOffice without invoking a shell."""

    command = [
        "soffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(pdf_path.parent),
        str(docx_path),
    ]
    if runner is None:
        subprocess.run(command, check=True, capture_output=True, text=True)
    else:
        runner(command)
    generated = pdf_path.parent / f"{docx_path.stem}.pdf"
    if generated != pdf_path and generated.exists():
        generated.replace(pdf_path)
    if not pdf_path.exists():
        raise ProposalDocumentError("LibreOffice did not create the requested PDF")


def _safe_paths(output_dir: Path, filename: str, include_pdf: bool) -> tuple[Path, Path | None]:
    if (
        not isinstance(filename, str)
        or not filename
        or filename in {".", ".."}
        or any(separator in filename for separator in ("/", "\\", ":"))
        or PurePosixPath(filename).name != filename
        or PureWindowsPath(filename).name != filename
        or PureWindowsPath(filename).drive
        or PureWindowsPath(filename).root
    ):
        raise ProposalDocumentError("filename must be a simple output name")
    stem = filename.removesuffix(".docx").removesuffix(".pdf")
    if not stem:
        raise ProposalDocumentError("filename must include a name")
    docx_path = output_dir / f"{stem}.docx"
    pdf_path = output_dir / f"{stem}.pdf" if include_pdf else None
    return docx_path, pdf_path


def _write_bytes(path: Path, content: bytes, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        try:
            with path.open("xb") as target:
                target.write(content)
        except FileExistsError as exc:
            raise ProposalDocumentError(f"refusing to overwrite existing output: {path}") from exc
        return
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temp:
        temp.write(content)
        temporary = Path(temp.name)
    os.replace(temporary, path)


def generate_proposal_documents(
    draft: QuotationDraft,
    quote: QuoteResult,
    output_dir: str | Path,
    *,
    filename: str = "quotation-proposal",
    language: Language = "en",
    pdf_converter: PdfConverter | None = None,
    overwrite: bool = False,
) -> ProposalDocuments:
    """Generate a proposal only from an approved draft and deterministic quote.

    PDF output is opt-in through ``pdf_converter``. Pass
    ``libreoffice_pdf_converter`` for local conversion, or inject a fake converter
    in tests. Existing outputs are never overwritten unless ``overwrite=True``.
    """

    approved_draft = require_approved_draft(draft)
    if not isinstance(quote, QuoteResult):
        raise ProposalDocumentError("quote must be a deterministic QuoteResult")
    if getattr(quote, "source_draft_fingerprint", None) != _draft_fingerprint(approved_draft):
        raise ProposalDocumentError("quote does not belong to the approved draft")
    _language(language)
    output_path = Path(output_dir)
    docx_path, pdf_path = _safe_paths(output_path, filename, pdf_converter is not None)
    if not overwrite and (docx_path.exists() or (pdf_path is not None and pdf_path.exists())):
        raise ProposalDocumentError("refusing to overwrite an existing proposal output")
    xml = _proposal_xml(approved_draft, quote, language)
    _write_bytes(docx_path, _docx_bytes(xml), overwrite=overwrite)
    docx_validation = validate_docx(docx_path)
    pdf_validation = None
    if pdf_converter is not None and pdf_path is not None:
        pdf_converter(docx_path, pdf_path)
        pdf_validation = validate_pdf(pdf_path)
    return ProposalDocuments(docx_path, pdf_path, docx_validation, pdf_validation)
