from datetime import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import JiraIssue, Agent
from app.schemas import VisitTicketUpdate
import app.routers.api as api_router

def test_calendar_endpoints():
    # 1. Setup in-memory SQLite DB
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # 2. Add an Agent and a JiraIssue that represents a scheduled visit
    agent = Agent(jira_account_id="jira-bob", name="Bob Agent", email="bob@test.com")
    db.add(agent)
    db.flush()

    issue = JiraIssue(
        jira_id="issue-visit-1",
        jira_key="MABC-101",
        summary="Visita Técnica Bob",
        project_key="MABC",
        issue_type="Asistencia Soporte TI",
        status="Open",
        raw_payload={
            "fields": {
                "customfield_10561": {"value": "Visita Programada"}, # Tipo atencion
                "customfield_10495": "ACME", # Client
                "customfield_10015": "2026-07-15", # Fecha inicio
                "duedate": "2026-07-15", # Fecha fin
                "customfield_10528": {"value": "L2"}, # SLA
                "customfield_10396": [{"value": "Estaciones de Trabajo"}], # Category
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Profesional Asignado: Bob Agent\nCliente: ACME\nInicio: 15/07/2026 10:00\nTérmino: 15/07/2026 12:00\n\nRevisión de hardware"}
                            ]
                        }
                    ]
                }
            }
        },
        assignee_agent_id=agent.id
    )
    db.add(issue)
    db.commit()

    # 3. Test GET /api/tickets/visits
    visits = api_router.get_visits(db=db)
    assert len(visits) == 1
    v = visits[0]
    assert v["id"] == "MABC-101"
    assert v["title"] == "Visita ACME - Bob Agent"
    # Ensure exact time was parsed from description text
    assert v["start"] == "2026-07-15T10:00:00"
    assert v["end"] == "2026-07-15T12:00:00"
    assert v["extendedProps"]["client"] == "ACME"
    assert v["extendedProps"]["agent_name"] == "Bob Agent"
    assert v["extendedProps"]["service_level"] == "L2"
    assert v["extendedProps"]["ticket_category"] == "Estaciones de Trabajo"
    assert "Revisión de hardware" in v["extendedProps"]["description"]

    # 4. Test PUT /api/tickets/visits/{key}
    with patch("app.services.jira.JiraClient") as mock_jira_class, \
         patch("app.services.sync.sync_single_issue_by_key") as mock_sync_func:
         
        mock_jira_instance = MagicMock()
        mock_jira_class.return_value = mock_jira_instance
        
        update_payload = VisitTicketUpdate(
            start_date=datetime(2026, 7, 20, 14, 00),
            end_date=datetime(2026, 7, 20, 16, 00),
            assignee_account_id="jira-bob",
            description="Revisión de redes",
            service_level="L2",
            ticket_category="Redes"
        )
        
        res = api_router.update_visit_ticket("MABC-101", update_payload, db=db)
        assert res["status"] == "ok"
        assert res["key"] == "MABC-101"
        
        # Verify update_issue was called with expected fields
        mock_jira_instance.update_issue.assert_called_once()
        called_args = mock_jira_instance.update_issue.call_args[0]
        assert called_args[0] == "MABC-101"
        
        fields_sent = called_args[1]
        assert fields_sent["customfield_10015"] == "2026-07-20"
        assert fields_sent["duedate"] == "2026-07-20"
        assert fields_sent["assignee"] == {"accountId": "jira-bob"}
        
        # Verify sync was called
        mock_sync_func.assert_called_once_with(db, "MABC-101")
        
    db.close()
