from datetime import date, datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Agent, Client, JiraIssue, JiraWorklog
from app.services.reports import build_hours_consumption_report
from app.services.pdf_report import generate_hours_consumption_pdf


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


def test_build_hours_consumption_report(db_session: Session):
    # Setup test agent, client, issue and worklogs
    agent = Agent(jira_account_id="ag-1", name="Juan Pérez", active=True)
    client = Client(jira_account_id="cl-1", name="Empresa ABC", active=True)
    db_session.add_all([agent, client])
    db_session.commit()

    issue = JiraIssue(
        jira_id="10001",
        jira_key="PROJ-101",
        summary="Soporte Servidor Linux",
        project_key="PROJ",
        issue_type="Support",
        status="Closed",
        reporter_client_id=client.id,
        assignee_agent_id=agent.id,
        created_at_jira=datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc),
        raw_payload={"fields": {"customfield_10010": "Empresa ABC", "customfield_10020": "L1/L2"}}
    )
    db_session.add(issue)
    db_session.commit()

    w1 = JiraWorklog(
        jira_worklog_id="wl-1",
        issue_id=issue.id,
        author_agent_id=agent.id,
        started_at=datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc),
        time_spent_seconds=7200, # 2 hours
        comment="Instalación de parches"
    )
    w2 = JiraWorklog(
        jira_worklog_id="wl-2",
        issue_id=issue.id,
        author_agent_id=agent.id,
        started_at=datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc),
        time_spent_seconds=3600, # 1 hour
        comment="Configuración de firewall"
    )
    db_session.add_all([w1, w2])
    db_session.commit()

    report = build_hours_consumption_report(
        db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    assert report["kpis"]["total_hours"] == 3.0
    assert report["kpis"]["total_worklogs"] == 2
    assert report["kpis"]["total_tickets"] == 1
    assert report["kpis"]["avg_hours_per_ticket"] == 3.0
    assert len(report["clients"]) == 1
    assert report["clients"][0]["hours_logged"] == 3.0
    assert len(report["agents"]) == 1
    assert report["agents"][0]["agent_name"] == "Juan Pérez"
    assert len(report["tickets"]) == 1
    assert report["tickets"][0]["jira_key"] == "PROJ-101"
    assert len(report["statuses"]) == 1
    assert report["statuses"][0]["status_name"] == "Closed"

    # Test multi-status filtering
    report_filtered = build_hours_consumption_report(
        db_session,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        statuses=["Pendiente", "En Espera"]
    )
    assert report_filtered["kpis"]["total_hours"] == 0.0


def test_generate_hours_consumption_pdf():
    sample_data = {
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "kpis": {
            "total_hours": 15.5,
            "total_worklogs": 5,
            "total_tickets": 3,
            "avg_hours_per_ticket": 5.17,
            "top_client_name": "Empresa ABC",
            "top_client_hours": 10.0,
            "top_agent_name": "Juan Pérez",
            "top_agent_hours": 15.5,
        },
        "clients": [
            {"client_name": "Empresa ABC", "hours_logged": 10.0, "ticket_count": 2, "percentage": 64.5},
            {"client_name": "Empresa XYZ", "hours_logged": 5.5, "ticket_count": 1, "percentage": 35.5},
        ],
        "agents": [
            {"agent_id": 1, "agent_name": "Juan Pérez", "hours_logged": 15.5, "ticket_count": 3, "percentage": 100.0},
        ],
        "service_levels": [
            {"service_level": "L1/L2", "hours_logged": 15.5, "ticket_count": 3, "percentage": 100.0},
        ],
        "statuses": [
            {"status_name": "Pendiente", "hours_logged": 10.0, "ticket_count": 2, "percentage": 64.5},
            {"status_name": "En Espera", "hours_logged": 5.5, "ticket_count": 1, "percentage": 35.5},
        ],
        "tickets": [
            {
                "jira_key": "PROJ-101",
                "summary": "Soporte Servidor Linux",
                "client_name": "Empresa ABC",
                "agent_name": "Juan Pérez",
                "service_level": "L1/L2",
                "hours_logged": 10.0,
                "worklog_count": 3,
            }
        ],
        "daily_series": [
            {"date": "2026-05-01", "hours": 5.0},
            {"date": "2026-05-02", "hours": 10.5},
        ],
    }

    pdf_bytes = generate_hours_consumption_pdf(sample_data, status_filter_label="Pendiente, En Espera")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF-")
