from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from quotation_agents import (
    ApprovalState,
    CommercialBudget,
    CommercialComponent,
    CommercialDeliverable,
    CommercialEstimation,
    CommercialPayment,
    CommercialProposal,
    CommercialTaskItem,
    CommercialUnderstanding,
    DraftApprovalRequiredError,
    QuotationDraft,
    QuotationTask,
    WorkCategory,
    build_commercial_proposal_from_quote,
    calculate_quote,
    generate_commercial_proposal_documents,
    split_modules,
    synthesize_commercial_proposal,
    validate_docx,
)


def task(category: WorkCategory, description: str, hours: str) -> QuotationTask:
    return QuotationTask(
        category=category,
        description=description,
        estimated_hours=Decimal(hours),
    )


def approved_draft(tasks: list[QuotationTask]) -> QuotationDraft:
    return QuotationDraft(
        client_company="Cableclub",
        original_request="Sistema de Campañas y Beneficios para clientes TV e Internet",
        inferred_scope=["Sistema de Campañas y Beneficios Cableclub"],
        assumptions=["Se provee acceso a nómina para ETL"],
        risks=["Calidad inicial de datos de nómina"],
        questions=["¿Qué pasarela de correo se usará?"],
        tasks=tasks,
        approval_state=ApprovalState.APPROVED,
    )


def docx_text(path: Path) -> str:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return "\n".join(text for text in root.itertext() if text)


def test_cableclub_example_json_matches_model() -> None:
    example_path = (
        Path(__file__).parents[1] / "templates" / "proposal_cableclub_example.json"
    )
    assert example_path.exists()
    content = example_path.read_text(encoding="utf-8")
    proposal = CommercialProposal.model_validate_json(content)
    assert proposal.client_name == "Cableclub"
    assert proposal.provider_name == "Daniel Calcina"
    assert len(proposal.understanding.components) == 8
    assert proposal.estimation.total_cost == Decimal("2700.00")
    assert len(proposal.deliverables) == 3


def test_build_commercial_proposal_deterministically() -> None:
    tasks = [
        task(WorkCategory.BACKEND, "CRUD de Campañas y Beneficios", "14"),
        task(WorkCategory.FRONTEND, "Módulo Asesor Comercial", "25"),
        task(WorkCategory.DEVOPS, "Configuración de despliegue Docker", "14"),
    ]
    draft = approved_draft(tasks)
    modules = split_modules(
        tasks,
        {
            "Backend API": [0],
            "Frontend Asesor": [1],
            "Deploy Docker": [2],
        },
    )
    quote = calculate_quote(draft, modules=modules)
    proposal = build_commercial_proposal_from_quote(
        draft,
        quote,
        project_name="Sistema de Campañas y Beneficios",
        provider_name="Daniel Calcina",
        modules=modules,
        discount=Decimal("100.00"),
    )

    assert proposal.project_name == "Sistema de Campañas y Beneficios"
    assert proposal.client_name == "Cableclub"
    assert proposal.provider_name == "Daniel Calcina"
    assert len(proposal.estimation.tasks) == 3
    assert proposal.estimation.discount == Decimal("100.00")
    assert proposal.estimation.total_hours == Decimal("53")
    assert len(proposal.payment_schedule) == len(quote.payment_schedule.payments)
    assert len(proposal.deliverables) == len(proposal.payment_schedule)


def test_synthesize_commercial_proposal_with_mock_invoke() -> None:
    tasks = [task(WorkCategory.BACKEND, "API de Campañas", "14")]
    draft = approved_draft(tasks)
    quote = calculate_quote(draft)

    mock_response = {
        "structured_response": {
            "project_name": "Sistema Cableclub",
            "client_name": "Cableclub",
            "provider_name": "Daniel Calcina",
            "understanding": {
                "summary": "Sistema web para fidelización de clientes.",
                "components": [
                    {"title": "Módulo Campañas", "description": "Gestión integral de beneficios"}
                ],
            },
            "estimation": {
                "tasks": [{"name": "Módulo Campañas", "hours": 14, "cost": 420.00}],
                "discount": 0,
                "total_hours": 14,
                "total_cost": 420.00,
            },
            "budget": {
                "estimated_duration": "14 horas / 1 semana",
                "investment_summary": "S/. 420.00 PEN en total",
                "includes": ["Backend completo"],
                "excludes": ["Hosting"],
            },
            "payment_schedule": [
                {
                    "milestone_label": "Pago único",
                    "amount": 420.00,
                    "condition": "contra entrega",
                }
            ],
            "deliverables": [
                {"name": "Entregable 1", "content": "Código fuente y despliegue"}
            ],
        }
    }

    proposal = synthesize_commercial_proposal(
        draft,
        quote,
        invoke=lambda _: mock_response,
    )
    assert proposal.project_name == "Sistema Cableclub"
    assert proposal.estimation.total_cost == Decimal("420.00")


def test_generate_commercial_proposal_docx(tmp_path: Path) -> None:
    example_path = (
        Path(__file__).parents[1] / "templates" / "proposal_cableclub_example.json"
    )
    proposal = CommercialProposal.model_validate_json(example_path.read_text(encoding="utf-8"))

    docs = generate_commercial_proposal_documents(
        proposal,
        tmp_path,
        filename="propuesta-cableclub",
    )

    assert docs.docx_validation.valid is True
    assert docs.docx_path.exists()

    content = docx_text(docs.docx_path)
    assert "Sistema de Campanas y Beneficios Cableclub" in content or "Cableclub" in content
    assert "Daniel Calcina" in content
    assert "1. Entendimiento del proyecto" in content
    assert "2. Estimacion horas por tareas" in content
    assert "3. Presupuesto estimado" in content
    assert "4. Pago" in content
    assert "5. Entregables" in content
    assert "S/. 2700.00" in content
    assert "-S/. 300.00" in content
