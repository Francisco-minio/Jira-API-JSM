from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Agent, Client, JiraIssue, JiraWorklog
from app.mcp_server import (
    get_hours_consumption,
    get_visits_report,
    get_client_tickets,
    list_clients,
    list_agents,
    list_statuses,
)


@pytest.fixture
def test_data():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()

    agent = Agent(jira_account_id="ag-mcp", name="Ana Morales", active=True)
    client = Client(jira_account_id="cl-mcp", name="AquaTech Chile", active=True)
    session.add_all([agent, client])
    session.commit()

    issue = JiraIssue(
        jira_id="30001",
        jira_key="MCP-101",
        summary="Visita Mantenimiento AquaTech",
        project_key="MCP",
        issue_type="Support",
        status="Closed",
        reporter_client=client,
        assignee_agent=agent,
        created_at_jira=datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc),
        raw_payload={
            "fields": {
                "customfield_10495": "AquaTech Chile",
                "customfield_10561": {"value": "Visita Programada", "id": "10406"},
            }
        },
    )
    session.add(issue)
    session.commit()

    wl = JiraWorklog(
        jira_worklog_id="wl-mcp-1",
        issue_id=issue.id,
        author_agent=agent,
        started_at=datetime(2026, 6, 10, 11, 0, tzinfo=timezone.utc),
        time_spent_seconds=7200,
        comment="Instalación de sensores",
    )
    session.add(wl)
    session.commit()

    try:
        yield session, test_engine
    finally:
        session.close()


def test_mcp_hours_consumption(monkeypatch, test_data):
    session, engine = test_data
    monkeypatch.setattr("app.mcp_server.SessionLocal", lambda: session)

    res = get_hours_consumption(start_date="2026-06-01", end_date="2026-06-30")
    assert res["kpis"]["total_hours"] == 2.0
    assert res["kpis"]["total_tickets"] == 1


def test_mcp_visits_report(monkeypatch, test_data):
    session, engine = test_data
    monkeypatch.setattr("app.mcp_server.SessionLocal", lambda: session)

    res = get_visits_report(start_date="2026-06-01", end_date="2026-06-30")
    assert res["kpis"]["total_visits"] == 1
    assert res["kpis"]["scheduled_visits"] == 1
    assert res["kpis"]["unscheduled_visits"] == 0


def test_mcp_listings(monkeypatch, test_data):
    session, engine = test_data
    monkeypatch.setattr("app.mcp_server.SessionLocal", lambda: session)

    clients = list_clients()
    assert len(clients) == 1
    assert clients[0]["name"] == "AquaTech Chile"

    agents = list_agents()
    assert len(agents) == 1
    assert agents[0]["name"] == "Ana Morales"

    statuses = list_statuses()
    assert "Closed" in statuses
