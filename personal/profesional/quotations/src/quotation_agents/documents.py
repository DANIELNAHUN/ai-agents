"""Deterministic DOCX proposal generation for approved quotation results."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal
from xml.etree import ElementTree as ET

from .commercial import PAYMENT_LABELS_ES, CommercialProposal, enforce_soles
from .models import QuotationDraft, QuotationTask, WorkCategory
from .pricing import QuoteResult, _draft_fingerprint
from .review import review_quote
from .workflow import require_approved_draft

Language = Literal["en", "es"]
PdfConverter = Callable[[Path, Path], None]
PdfRunner = Callable[[Sequence[str]], object]

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_R = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("w", _W)
ET.register_namespace("", _CT)
_OR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("r", _OR)


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
        "band": "Band",
        "band_amount": "Amount (PEN)",
        "hours_unit": "hours",
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
        "band": "Rango",
        "band_amount": "Monto (PEN)",
        "hours_unit": "horas",
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


_PAYMENT_LABELS = {"es": PAYMENT_LABELS_ES}


def _task_text(task: QuotationTask, text: dict[str, str]) -> str:
    if task.estimated_hours is None:
        return task.description
    return f"{task.description} ({task.estimated_hours} {text['hours_unit']})"


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
            body.append(_paragraph(_task_text(task, text)))

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
                [text["band"], text["band_amount"]],
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
        label = _PAYMENT_LABELS.get(language, {}).get(payment.label, payment.label)
        payment_rows.append([label, _money(payment.amount), share])
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


@dataclass(frozen=True)
class _Part:
    """An extra package part referenced from ``word/document.xml``."""

    name: str
    content: bytes
    content_type: str
    relationship_type: str
    relationship_id: str


def _docx_bytes(document_xml: bytes, parts: Sequence[_Part] = ()) -> bytes:
    overrides = "".join(
        f'<Override PartName="/word/{part.name}" ContentType="{part.content_type}"/>'
        for part in parts
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_CT}">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        f"{overrides}"
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
    part_relationships = "".join(
        f'<Relationship Id="{part.relationship_id}" Type="{part.relationship_type}" '
        f'Target="{part.name}"/>'
        for part in parts
    )
    document_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_R}">{part_relationships}</Relationships>'
    ).encode()
    package = (
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", relationships),
        ("word/document.xml", document_xml),
        ("word/_rels/document.xml.rels", document_relationships),
        *((f"word/{part.name}", part.content) for part in parts),
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in package:
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
    review = review_quote(approved_draft, quote)
    if not review.passed:
        codes = ", ".join(issue.code for issue in review.errors)
        raise ProposalDocumentError(
            f"quotation review failed; correct error findings: {codes}"
        )
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


# Commercial proposal layout, mirroring the approved client template
# (Arial, US Letter, centered title, numbered headings, bordered estimation table).
_FONT = "Arial"
_BODY_SIZE = 22  # half-points: 11pt
_META_SIZE = 24  # 12pt
_HEADING_SIZE = 28  # 14pt
_TITLE_SIZE = 32  # 16pt
_FOOTER_SIZE = 20  # 10pt
_FOOTER_COLOR = "434343"
_TABLE_COLUMNS = (5000, 2180, 2180)
_BULLET_NUM_ID = "1"
_DASH_NUM_ID = "2"
_FOOTER_REL_ID = "rId3"
_REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WML_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _set(parent: ET.Element, tag: str, **attributes: str) -> ET.Element:
    return ET.SubElement(parent, _w(tag), {_w(key): value for key, value in attributes.items()})


def _run(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    size: int = _BODY_SIZE,
    color: str | None = None,
) -> ET.Element:
    run = ET.Element(_w("r"))
    properties = _set(run, "rPr")
    if bold:
        _set(properties, "b")
        _set(properties, "bCs")
    if italic:
        _set(properties, "i")
        _set(properties, "iCs")
    if color:
        _set(properties, "color", val=color)
    _set(properties, "sz", val=str(size))
    _set(properties, "szCs", val=str(size))
    node = _set(run, "t")
    node.set(_XML_SPACE, "preserve")
    node.text = text
    return run


def _rich_paragraph(
    *runs: ET.Element,
    style: str | None = None,
    align: str | None = None,
    before: int = 0,
    after: int = 0,
    keep_next: bool = False,
    num_id: str | None = None,
) -> ET.Element:
    paragraph = ET.Element(_w("p"))
    properties = _set(paragraph, "pPr")
    if style:
        _set(properties, "pStyle", val=style)
    if keep_next:
        _set(properties, "keepNext")
    if num_id:
        numbering = _set(properties, "numPr")
        _set(numbering, "ilvl", val="0")
        _set(numbering, "numId", val=num_id)
    if not style:
        _set(properties, "spacing", before=str(before), after=str(after))
    if align:
        _set(properties, "jc", val=align)
    paragraph.extend(runs)
    return paragraph


def _labeled(label: str, value: str, *, size: int = _BODY_SIZE) -> ET.Element:
    return _rich_paragraph(_run(label, bold=True, size=size), _run(value, size=size), after=40)


def _heading(text: str) -> ET.Element:
    return _rich_paragraph(_run(text, bold=True, size=_HEADING_SIZE), style="Heading1")


def _cost(value: Decimal) -> str:
    return f"S/. {value:.2f}"


def _hours(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _estimation_table(proposal: CommercialProposal) -> ET.Element:
    estimation = proposal.estimation
    rows: list[tuple[tuple[str, str, str], bool]] = [
        (("TAREAS", "HORAS TOTAL", "COSTO TOTAL"), True),
        *(((task.name, _hours(task.hours), _cost(task.cost)), False) for task in estimation.tasks),
    ]
    if estimation.discount > 0:
        rows.append((("Descuento", "", f"-{_cost(estimation.discount)}"), False))
    rows.append((("TOTAL", _hours(estimation.total_hours), _cost(estimation.total_cost)), True))

    table = ET.Element(_w("tbl"))
    properties = _set(table, "tblPr")
    _set(properties, "tblW", w=str(sum(_TABLE_COLUMNS)), type="dxa")
    borders = _set(properties, "tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _set(borders, side, val="single", sz="8", space="0", color="000000")
    _set(properties, "tblLayout", type="fixed")
    margins = _set(properties, "tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        _set(margins, side, w="100", type="dxa")
    grid = _set(table, "tblGrid")
    for width in _TABLE_COLUMNS:
        _set(grid, "gridCol", w=str(width))

    for index, (values, bold) in enumerate(rows):
        header = index == 0
        row = _set(table, "tr")
        row_properties = _set(row, "trPr")
        _set(row_properties, "cantSplit")
        _set(row_properties, "trHeight", val="418", hRule="atLeast")
        if header:
            _set(row_properties, "tblHeader")
        aligns = ("center",) * 3 if header else ("left", "center", "right")
        for value, width, align in zip(values, _TABLE_COLUMNS, aligns):
            cell = _set(row, "tc")
            cell_properties = _set(cell, "tcPr")
            _set(cell_properties, "tcW", w=str(width), type="dxa")
            _set(cell_properties, "vAlign", val="center")
            cell.append(_rich_paragraph(_run(value, bold=bold), align=align))
    return table


def _commercial_proposal_xml(proposal: CommercialProposal) -> bytes:
    document = ET.Element(_w("document"))
    body = _set(document, "body")

    body.append(
        _rich_paragraph(
            _run(f"Propuesta Comercial — {proposal.project_name}", bold=True, size=_TITLE_SIZE),
            align="center",
            after=320,
        )
    )
    body.append(_labeled("Proyecto: ", proposal.project_name, size=_META_SIZE))
    body.append(_labeled("Cliente: ", proposal.client_name, size=_META_SIZE))
    body.append(_labeled("Proveedor: ", proposal.provider_name, size=_META_SIZE))

    body.append(_heading("1. Entendimiento del proyecto"))
    body.append(_rich_paragraph(_run(proposal.understanding.summary), after=120))
    body.append(_rich_paragraph(_run("La solución considera estos módulos:"), after=60))
    for component in proposal.understanding.components:
        body.append(
            _rich_paragraph(
                _run(component.title, bold=True),
                _run(f": {component.description}"),
                num_id=_DASH_NUM_ID,
                after=60,
            )
        )

    body.append(_heading("2. Estimación horas por tareas"))
    body.append(_estimation_table(proposal))

    budget = proposal.budget
    body.append(_heading("3. Presupuesto estimado"))
    body.append(_labeled("Total estimado: ", budget.estimated_duration))
    body.append(_labeled("Inversión estimada: ", budget.investment_summary))
    for label, items in (("Incluye:", budget.includes), ("No incluye:", budget.excludes)):
        body.append(_rich_paragraph(_run(label, bold=True), before=160, after=40, keep_next=True))
        for item in items:
            body.append(_rich_paragraph(_run(item), num_id=_BULLET_NUM_ID, after=20))

    body.append(_heading("4. Pago"))
    for payment in proposal.payment_schedule:
        body.append(
            _rich_paragraph(
                _run(payment.milestone_label, bold=True),
                _run(f" de {_cost(payment.amount)} {payment.condition}"),
                after=60,
            )
        )

    body.append(_heading("5. Entregables"))
    for deliverable in proposal.deliverables:
        body.append(_labeled(f"{deliverable.name}: ", deliverable.content))

    section = _set(body, "sectPr")
    ET.SubElement(
        section, _w("footerReference"), {_w("type"): "default", f"{{{_OR}}}id": _FOOTER_REL_ID}
    )
    _set(section, "pgSz", w="12240", h="15840")
    _set(
        section,
        "pgMar",
        top="1000",
        right="1440",
        bottom="1000",
        left="1315",
        header="0",
        footer="500",
        gutter="0",
    )
    return ET.tostring(document, encoding="utf-8", xml_declaration=True)


def _commercial_styles_xml() -> bytes:
    styles = ET.Element(_w("styles"))
    defaults = _set(styles, "docDefaults")
    run_defaults = _set(_set(defaults, "rPrDefault"), "rPr")
    _set(run_defaults, "rFonts", ascii=_FONT, hAnsi=_FONT, eastAsia=_FONT, cs=_FONT)
    _set(run_defaults, "color", val="000000")
    _set(run_defaults, "sz", val=str(_BODY_SIZE))
    _set(run_defaults, "szCs", val=str(_BODY_SIZE))
    _set(run_defaults, "lang", val="es-PE")
    paragraph_defaults = _set(_set(defaults, "pPrDefault"), "pPr")
    _set(paragraph_defaults, "spacing", after="0", line="264", lineRule="auto")

    normal = _set(styles, "style", type="paragraph", default="1", styleId="Normal")
    _set(normal, "name", val="Normal")
    _set(normal, "qFormat")

    heading = _set(styles, "style", type="paragraph", styleId="Heading1")
    _set(heading, "name", val="heading 1")
    _set(heading, "basedOn", val="Normal")
    _set(heading, "next", val="Normal")
    _set(heading, "qFormat")
    heading_paragraph = _set(heading, "pPr")
    _set(heading_paragraph, "keepNext")
    _set(heading_paragraph, "keepLines")
    _set(heading_paragraph, "spacing", before="400", after="160")
    _set(heading_paragraph, "outlineLvl", val="0")
    heading_run = _set(heading, "rPr")
    _set(heading_run, "rFonts", ascii=_FONT, hAnsi=_FONT, eastAsia=_FONT, cs=_FONT)
    _set(heading_run, "b")
    _set(heading_run, "bCs")
    _set(heading_run, "sz", val=str(_HEADING_SIZE))
    _set(heading_run, "szCs", val=str(_HEADING_SIZE))

    table = _set(styles, "style", type="table", default="1", styleId="TableNormal")
    _set(table, "name", val="Normal Table")
    return ET.tostring(styles, encoding="utf-8", xml_declaration=True)


def _commercial_numbering_xml() -> bytes:
    numbering = ET.Element(_w("numbering"))
    for abstract_id, symbol in (("0", "•"), ("1", "-")):
        abstract = _set(numbering, "abstractNum", abstractNumId=abstract_id)
        _set(abstract, "multiLevelType", val="singleLevel")
        level = _set(abstract, "lvl", ilvl="0")
        _set(level, "start", val="1")
        _set(level, "numFmt", val="bullet")
        _set(level, "lvlText", val=symbol)
        _set(level, "lvlJc", val="left")
        _set(_set(level, "pPr"), "ind", left="360", hanging="240")
        _set(_set(level, "rPr"), "rFonts", ascii=_FONT, hAnsi=_FONT, cs=_FONT, hint="default")
    for num_id, abstract_id in ((_BULLET_NUM_ID, "0"), (_DASH_NUM_ID, "1")):
        number = _set(numbering, "num", numId=num_id)
        _set(number, "abstractNumId", val=abstract_id)
    return ET.tostring(numbering, encoding="utf-8", xml_declaration=True)


def _commercial_footer_xml(proposal: CommercialProposal) -> bytes:
    footer = ET.Element(_w("ftr"))

    def footer_run(text: str) -> ET.Element:
        return _run(text, italic=True, size=_FOOTER_SIZE, color=_FOOTER_COLOR)

    page = _rich_paragraph(footer_run("Página "), align="center")
    _set(ET.SubElement(page, _w("r")), "fldChar", fldCharType="begin")
    instruction = _set(ET.SubElement(page, _w("r")), "instrText")
    instruction.set(_XML_SPACE, "preserve")
    instruction.text = "PAGE"
    _set(ET.SubElement(page, _w("r")), "fldChar", fldCharType="separate")
    page.append(footer_run("1"))
    _set(ET.SubElement(page, _w("r")), "fldChar", fldCharType="end")
    footer.append(page)
    footer.append(
        _rich_paragraph(
            footer_run(f"{proposal.client_name} - {proposal.project_name}"), align="right"
        )
    )
    return ET.tostring(footer, encoding="utf-8", xml_declaration=True)


def _commercial_parts(proposal: CommercialProposal) -> tuple[_Part, ...]:
    return (
        _Part(
            "styles.xml",
            _commercial_styles_xml(),
            f"{_WML_CT}.styles+xml",
            f"{_REL_BASE}/styles",
            "rId1",
        ),
        _Part(
            "numbering.xml",
            _commercial_numbering_xml(),
            f"{_WML_CT}.numbering+xml",
            f"{_REL_BASE}/numbering",
            "rId2",
        ),
        _Part(
            "footer1.xml",
            _commercial_footer_xml(proposal),
            f"{_WML_CT}.footer+xml",
            f"{_REL_BASE}/footer",
            _FOOTER_REL_ID,
        ),
    )


def generate_commercial_proposal_documents(
    proposal: CommercialProposal,
    output_dir: str | Path,
    *,
    filename: str = "commercial-proposal",
    pdf_converter: PdfConverter | None = None,
    overwrite: bool = False,
) -> ProposalDocuments:
    """Generate a client-facing proposal DOCX/PDF following the client template."""

    if not isinstance(proposal, CommercialProposal):
        raise ProposalDocumentError("proposal must be an instance of CommercialProposal")

    output_path = Path(output_dir)
    docx_path, pdf_path = _safe_paths(output_path, filename, pdf_converter is not None)
    if not overwrite and (docx_path.exists() or (pdf_path is not None and pdf_path.exists())):
        raise ProposalDocumentError("refusing to overwrite an existing proposal output")

    proposal, _ = enforce_soles(proposal)
    xml = _commercial_proposal_xml(proposal)
    package = _docx_bytes(xml, _commercial_parts(proposal))
    _write_bytes(docx_path, package, overwrite=overwrite)
    docx_validation = validate_docx(docx_path)
    pdf_validation = None
    if pdf_converter is not None and pdf_path is not None:
        pdf_converter(docx_path, pdf_path)
        pdf_validation = validate_pdf(pdf_path)
    return ProposalDocuments(docx_path, pdf_path, docx_validation, pdf_validation)

