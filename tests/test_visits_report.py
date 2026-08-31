from datetime import date, datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Agent, Client, JiraIssue, JiraWorklog
from app.services.reports import build_visits_report
from app.services.pdf_report import generate_visits_report_pdf


@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def test_build_visits_report(db_session: Session):
    agent = Agent(jira_account_id="ag-1", name="Carlos Gómez", active=True)
    client = Client(jira_account_id="cl-1", name="Empresa Pesquera", active=True)
    db_session.add_all([agent, client])
    db_session.commit()

    # Issue 1: Scheduled visit
    i1 = JiraIssue(
        jira_id="20001",
        jira_key="PROJ-201",
        summary="Visita Mantenimiento Preventivo 15/05/2026",
        project_key="PROJ",
        issue_type="Support",
        status="Closed",
        reporter_client=client,
        assignee_agent=agent,
        created_at_jira=datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc),
        raw_payload={
            "fields": {
                "customfield_10495": "Empresa Pesquera",
                "customfield_10561": {"value": "Visita Programada", "id": "10406"},
            }
        },
    )
    # Issue 2: Unscheduled visit
    i2 = JiraIssue(
        jira_id="20002",
        jira_key="PROJ-202",
        summary="Visita No Programada Emergencia Servidor",
        project_key="PROJ",
        issue_type="Support",
        status="Closed",
        reporter_client=client,
        assignee_agent=agent,
        created_at_jira=datetime(2026, 5, 20, 14, 0, tzinfo=timezone.utc),
        raw_payload={
            "fields": {
                "customfield_10495": "Empresa Pesquera",
                "customfield_10561": {"value": "Visita No Programada", "id": "10407"},
            }
        },
    )
    db_session.add_all([i1, i2])
    db_session.commit()

    w1 = JiraWorklog(
        jira_worklog_id="wl-10",
        issue_id=i1.id,
        author_agent_id=agent.id,
        started_at=datetime(2026, 5, 15, 11, 0, tzinfo=timezone.utc),
        time_spent_seconds=7200,  # 2 hours
        comment="Revisión de rack",
    )
    w2 = JiraWorklog(
        jira_worklog_id="wl-11",
        issue_id=i2.id,
        author_agent_id=agent.id,
        started_at=datetime(2026, 5, 20, 15, 0, tzinfo=timezone.utc),
        time_spent_seconds=10800,  # 3 hours
        comment="Reemplazo de disco en caliente",
    )
    db_session.add_all([w1, w2])
    db_session.commit()

    report = build_visits_report(
        db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    assert report["kpis"]["total_visits"] == 2
    assert report["kpis"]["scheduled_visits"] == 1
    assert report["kpis"]["unscheduled_visits"] == 1
    assert report["kpis"]["total_hours"] == 5.0
    assert report["kpis"]["avg_hours_per_visit"] == 2.5
    assert len(report["types"]) == 2
    assert len(report["clients"]) == 1
    assert report["clients"][0]["client_name"] == "Empresa Pesquera"
    assert report["clients"][0]["total_visits"] == 2
    assert len(report["tickets"]) == 2


def test_generate_visits_report_pdf():
    sample_data = {
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "kpis": {
            "total_visits": 10,
            "scheduled_visits": 7,
            "unscheduled_visits": 3,
            "total_hours": 32.5,
            "avg_hours_per_visit": 3.25,
            "top_client_name": "Empresa Pesquera",
            "top_client_visits": 6,
        },
        "types": [
            {"visit_type": "Visita Programada", "visit_count": 7, "hours_logged": 22.5, "percentage": 69.2},
            {"visit_type": "Visita No Programada", "visit_count": 3, "hours_logged": 10.0, "percentage": 30.8},
        ],
        "clients": [
            {"client_name": "Empresa Pesquera", "scheduled_count": 5, "unscheduled_count": 1, "total_visits": 6, "hours_logged": 20.0},
            {"client_name": "Empresa Mar", "scheduled_count": 2, "unscheduled_count": 2, "total_visits": 4, "hours_logged": 12.5},
        ],
        "agents": [
            {"agent_id": 1, "agent_name": "Carlos Gómez", "scheduled_count": 7, "unscheduled_count": 3, "total_visits": 10, "hours_logged": 32.5},
        ],
        "tickets": [
            {
                "jira_key": "PROJ-201",
                "summary": "Visita Mantenimiento Preventivo",
                "client_name": "Empresa Pesquera",
                "agent_name": "Carlos Gómez",
                "visit_type": "Visita Programada",
                "visit_date": "2026-05-15",
                "hours_logged": 2.0,
                "status": "Cerrado",
            }
        ],
        "daily_series": [
            {"date": "2026-05-15", "scheduled_count": 1, "unscheduled_count": 0, "total_visits": 1},
        ],
    }

    pdf_bytes = generate_visits_report_pdf(sample_data, visit_type_filter_label="Todas las visitas")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF-")
