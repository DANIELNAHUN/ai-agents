from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from quotation_agents import (
    ApprovalState,
    CommercialProposal,
    QuotationDraft,
    QuotationTask,
    WorkCategory,
    build_commercial_proposal_from_quote,
    calculate_quote,
    enforce_soles,
    generate_commercial_proposal_documents,
    split_modules,
    synthesize_commercial_proposal,
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
    row_costs = sum(row.cost for row in proposal.estimation.tasks)
    assert row_costs - proposal.estimation.discount == quote.selected_amount
    assert len(proposal.payment_schedule) == len(quote.payment_schedule.payments)
    assert len(proposal.deliverables) == len(proposal.payment_schedule)


def test_synthesize_commercial_proposal_with_mock_invoke() -> None:
    tasks = [task(WorkCategory.BACKEND, "API de Campañas", "14")]
    draft = approved_draft(tasks)
    quote = calculate_quote(draft)

    mock_response = {
        "structured_response": {
            "project_understanding": {
                "summary": "Sistema web para fidelización de clientes.",
                "components": [
                    {"title": "Módulo Campañas", "description": "Gestión integral de beneficios"}
                ],
            },
            "task_groups": [{"name": "Módulo Campañas", "task_numbers": [1]}],
            "budget_scope": {
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
    assert proposal.project_name == draft.inferred_scope[0]
    assert proposal.estimation.total_cost == quote.selected_amount
    assert [row.name for row in proposal.estimation.tasks] == ["Módulo Campañas"]
    assert proposal.estimation.tasks[0].cost == quote.selected_amount


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
    assert "2. Estimación horas por tareas" in content
    assert "3. Presupuesto estimado" in content
    assert "4. Pago" in content
    assert "5. Entregables" in content
    assert "S/. 2700.00" in content
    assert "-S/. 300.00" in content


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _example_docx(tmp_path: Path) -> Path:
    example_path = (
        Path(__file__).parents[1] / "templates" / "proposal_cableclub_example.json"
    )
    proposal = CommercialProposal.model_validate_json(example_path.read_text(encoding="utf-8"))
    return generate_commercial_proposal_documents(proposal, tmp_path).docx_path


def test_commercial_docx_follows_client_template_layout(tmp_path: Path) -> None:
    path = _example_docx(tmp_path)
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        document = ET.fromstring(archive.read("word/document.xml"))
        styles = archive.read("word/styles.xml").decode("utf-8")
        footer = ET.fromstring(archive.read("word/footer1.xml"))
        content_types = archive.read("[Content_Types].xml").decode("utf-8")
        rels = archive.read("word/_rels/document.xml.rels").decode("utf-8")

    assert {"word/styles.xml", "word/numbering.xml", "word/footer1.xml"} <= names
    assert "/word/footer1.xml" in content_types and "footer1.xml" in rels
    assert 'w:ascii="Arial"' in styles

    paragraphs = document.iter(f"{W}p")
    title = next(paragraphs)
    assert "".join(title.itertext()) == (
        "Propuesta Comercial — Sistema de Campañas y Beneficios Cableclub"
    )
    assert title.find(f"{W}pPr/{W}jc").get(f"{W}val") == "center"

    text = docx_text(path)
    for label in ("Proyecto: ", "Cliente: ", "Proveedor: ", "Total estimado: ",
                  "Inversión estimada: ", "Primer pago", "Entregable 1: "):
        assert label in text

    headings = [
        "".join(p.itertext())
        for p in document.iter(f"{W}p")
        if (style := p.find(f"{W}pPr/{W}pStyle")) is not None
        and style.get(f"{W}val") == "Heading1"
    ]
    assert headings == [
        "1. Entendimiento del proyecto",
        "2. Estimación horas por tareas",
        "3. Presupuesto estimado",
        "4. Pago",
        "5. Entregables",
    ]

    table = document.find(f".//{W}tbl")
    assert table.find(f"{W}tblPr/{W}tblBorders/{W}insideH").get(f"{W}val") == "single"
    assert len(table.findall(f"{W}tblGrid/{W}gridCol")) == 3
    rows = table.findall(f"{W}tr")
    assert [ "".join(c.itertext()) for c in rows[0].findall(f"{W}tc")] == [
        "TAREAS", "HORAS TOTAL", "COSTO TOTAL"
    ]
    assert rows[0].find(f"{W}trPr/{W}tblHeader") is not None
    total = rows[-1]
    assert ["".join(c.itertext()) for c in total.findall(f"{W}tc")] == [
        "TOTAL", "130", "S/. 2700.00"
    ]
    assert total.find(f".//{W}b") is not None

    bullets = [p for p in document.iter(f"{W}p") if p.find(f"{W}pPr/{W}numPr") is not None]
    assert len(bullets) == 8 + 8 + 4  # components + includes + excludes

    footer_text = "".join(footer.itertext())
    assert "Página" in footer_text
    assert "Cableclub - Sistema de Campañas y Beneficios Cableclub" in footer_text
    assert any(i.text == "PAGE" for i in footer.iter(f"{W}instrText"))


def test_commercial_synthesis_prompt_requires_spanish_output() -> None:
    from quotation_agents.commercial import COMMERCIAL_SYNTHESIS_SYSTEM_PROMPT

    assert "Write every client-facing text in Spanish" in COMMERCIAL_SYNTHESIS_SYSTEM_PROMPT


NOTIFICATION_TASKS = [
    task(WorkCategory.BACKEND, "Sistema de notificaciones de Venta", "5"),
    task(WorkCategory.FRONTEND, "Interfaz de Notificaciones", "10"),
    task(WorkCategory.BACKEND, "API de Campañas", "14"),
]


def synthesis_response(groups, **overrides):
    response = {
        "project_understanding": {
            "summary": "Sistema de notificaciones y campañas.",
            "components": [{"title": "Notificaciones", "description": "Avisos de venta"}],
        },
        "task_groups": groups,
        "budget_scope": {"includes": ["Backend"], "excludes": ["Hosting"]},
        "payment_schedule": [
            {"milestone_label": "Pago único", "amount": 100, "condition": "al inicio"}
        ],
        "deliverables": [{"name": "Entregable 1", "content": "Sistema completo"}],
    }
    response.update(overrides)
    return {"structured_response": response}


def synthesize_groups(groups, **overrides):
    draft = approved_draft(NOTIFICATION_TASKS)
    quote = calculate_quote(draft)
    requests = []

    def invoke(request):
        requests.append(request)
        return synthesis_response(groups, **overrides)

    proposal = synthesize_commercial_proposal(
        draft, quote, project_name="Sistema Ventas", provider_name="Daniel", invoke=invoke
    )
    return proposal, quote, requests


def test_synthesis_merges_related_tasks_into_one_row_with_computed_numbers() -> None:
    groups = [{"name": "Sistema de Notificaciones", "task_numbers": [1, 2]}]

    proposal, quote, requests = synthesize_groups(groups)

    rows = proposal.estimation.tasks
    assert [(row.name, row.hours) for row in rows] == [
        ("Sistema de Notificaciones", Decimal("15")),
        ("Desarrollo Backend y APIs", Decimal("14")),
    ]
    assert proposal.estimation.total_hours == Decimal("29") == quote.effort.total_hours
    assert sum(row.cost for row in rows) == proposal.estimation.total_cost
    assert proposal.estimation.total_cost == quote.selected_amount
    assert proposal.estimation.discount == Decimal("0")
    assert (proposal.project_name, proposal.client_name, proposal.provider_name) == (
        "Sistema Ventas",
        "Cableclub",
        "Daniel",
    )
    assert proposal.budget.investment_summary.startswith(f"S/. {quote.selected_amount:.2f}")
    assert "29 horas" in proposal.budget.estimated_duration
    user_message = requests[0]["messages"][1]["content"]
    assert "#1 [backend] Sistema de notificaciones de Venta (5h)" in user_message
    assert "#2 [frontend] Interfaz de Notificaciones (10h)" in user_message


def test_merged_row_costs_are_proportional_to_raw_cost_and_sum_exactly() -> None:
    groups = [
        {"name": "Sistema de Notificaciones", "task_numbers": [2, 1]},
        {"name": "Campañas", "task_numbers": [3]},
    ]

    proposal, quote, _ = synthesize_groups(groups)

    notifications, campaigns = proposal.estimation.tasks
    raw_notifications = Decimal("5") * 30 + Decimal("10") * 20
    raw_campaigns = Decimal("14") * 30
    raw_total = raw_notifications + raw_campaigns
    expected = quote.selected_amount * raw_notifications / raw_total
    assert abs(notifications.cost - expected) <= Decimal("0.01")
    assert notifications.cost + campaigns.cost == quote.selected_amount
    assert notifications.cost == notifications.cost.quantize(Decimal("0.01"))


def test_a_task_assigned_twice_stays_in_its_first_row() -> None:
    groups = [
        {"name": "Notificaciones", "task_numbers": [1, 2]},
        {"name": "Ventas", "task_numbers": [1, 3]},
    ]

    proposal, quote, _ = synthesize_groups(groups)

    rows = proposal.estimation.tasks
    assert [(row.name, row.hours) for row in rows] == [
        ("Notificaciones", Decimal("15")),
        ("Ventas", Decimal("14")),
    ]
    assert sum(row.cost for row in rows) == quote.selected_amount


def test_unknown_task_numbers_and_emptied_groups_are_ignored() -> None:
    groups = [
        {"name": "Notificaciones", "task_numbers": [1, 2, 3, 9]},
        {"name": "Fantasma", "task_numbers": [2, 0]},
    ]

    proposal, quote, _ = synthesize_groups(groups)

    rows = proposal.estimation.tasks
    assert [(row.name, row.hours) for row in rows] == [("Notificaciones", Decimal("29"))]
    assert rows[0].cost == quote.selected_amount


def test_synthesis_prompt_asks_to_merge_related_tasks_without_numbers() -> None:
    from quotation_agents.commercial import COMMERCIAL_SYNTHESIS_SYSTEM_PROMPT

    assert "Merge related technical tasks" in COMMERCIAL_SYNTHESIS_SYSTEM_PROMPT
    assert "Do not compute hours or costs" in COMMERCIAL_SYNTHESIS_SYSTEM_PROMPT


def _example_proposal() -> CommercialProposal:
    example_path = (
        Path(__file__).parents[1] / "templates" / "proposal_cableclub_example.json"
    )
    return CommercialProposal.model_validate_json(example_path.read_text(encoding="utf-8"))


def test_enforce_soles_replaces_dollar_amounts_and_words() -> None:
    proposal = _example_proposal()
    budget = proposal.budget.model_copy(
        update={
            "investment_summary": "$ 2,700.00 (2700 USD en total)",
            "includes": ["Soporte valorizado en US$300", "Pagos en dólares"],
        }
    )
    proposal = proposal.model_copy(update={"budget_summary": budget})

    fixed, findings = enforce_soles(proposal)

    assert fixed.budget.investment_summary == "S/. 2,700.00 (S/. 2700 en total)"
    assert fixed.budget.includes[:2] == ["Soporte valorizado en S/. 300", "Pagos en soles"]
    assert len(findings) == 3
    assert enforce_soles(fixed)[1] == ()


def test_enforce_soles_leaves_a_clean_proposal_unchanged() -> None:
    proposal = _example_proposal()

    fixed, findings = enforce_soles(proposal)

    assert findings == ()
    assert fixed == proposal


def test_commercial_docx_never_shows_dollars(tmp_path: Path) -> None:
    proposal = _example_proposal()
    payment = proposal.payment_schedule[0].model_copy(update={"condition": "monto en USD"})
    proposal = proposal.model_copy(
        update={"payment_schedule": [payment, *proposal.payment_schedule[1:]]}
    )
    budget = proposal.budget.model_copy(update={"investment_summary": "$2700"})
    proposal = proposal.model_copy(update={"budget_summary": budget})

    content = docx_text(generate_commercial_proposal_documents(proposal, tmp_path).docx_path)

    assert "$" not in content and "USD" not in content
    assert "S/. 2700" in content


def _payments(entries):
    groups = [{"name": "Sistema de Notificaciones", "task_numbers": [1, 2, 3]}]
    return synthesize_groups(groups, payment_schedule=entries)


def test_payment_amounts_come_from_the_quote_not_the_agent() -> None:
    entries = [
        {"milestone_label": "Primer pago", "amount": "S/. 1422.00", "condition": "al iniciar"},
        {"milestone_label": "Pago final", "amount": "S/. 2133.00", "condition": "al finalizar"},
    ]

    proposal, quote, requests = _payments(entries)

    expected = [payment.amount for payment in quote.payment_schedule.payments]
    assert len(expected) == 2
    assert [payment.amount for payment in proposal.payment_schedule] == expected
    assert [payment.milestone_label for payment in proposal.payment_schedule] == [
        "Primer pago",
        "Pago final",
    ]
    assert [payment.condition for payment in proposal.payment_schedule] == [
        "al iniciar",
        "al finalizar",
    ]
    assert "Adelanto: S/. " in requests[0]["messages"][1]["content"]


def test_missing_payment_milestones_are_filled_from_the_quote() -> None:
    proposal, quote, _ = _payments([{"milestone_label": "Primer pago", "condition": "al iniciar"}])

    second = proposal.payment_schedule[1]
    assert len(proposal.payment_schedule) == len(quote.payment_schedule.payments)
    assert second.milestone_label == "Cierre del proyecto"
    assert second.amount == quote.payment_schedule.payments[1].amount
    assert second.condition == "según el avance del proyecto"


def test_extra_payment_milestones_are_dropped() -> None:
    entries = [
        {"milestone_label": f"Pago {number}", "condition": "al avanzar"} for number in range(4)
    ]

    proposal, quote, _ = _payments(entries)

    assert len(proposal.payment_schedule) == len(quote.payment_schedule.payments)
    assert sum(p.amount for p in proposal.payment_schedule) == quote.selected_amount


def test_tasks_left_out_are_grouped_by_category_with_spanish_names() -> None:
    draft = approved_draft(
        [
            task(WorkCategory.BACKEND, "Notification service", "5"),
            task(WorkCategory.DEVOPS, "Set up Docker Compose deployment", "3"),
            task(WorkCategory.DEVOPS, "Configure CI pipeline", "2"),
        ]
    )
    quote = calculate_quote(draft)
    response = synthesis_response([{"name": "Notificaciones", "task_numbers": [1]}])

    proposal = synthesize_commercial_proposal(draft, quote, invoke=lambda _: response)

    assert [(row.name, row.hours) for row in proposal.estimation.tasks] == [
        ("Notificaciones", Decimal("5")),
        ("Despliegue e Infraestructura", Decimal("5")),
    ]


def test_payment_condition_prefix_is_removed() -> None:
    entries = [
        {"milestone_label": "Adelanto", "condition": "Condición: para iniciar el proyecto"},
        {"milestone_label": "Pago final", "condition": "condicion:al finalizar"},
    ]

    proposal, _, _ = _payments(entries)

    assert [p.condition for p in proposal.payment_schedule] == [
        "para iniciar el proyecto",
        "al finalizar",
    ]
