from datetime import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.db import Base
from app.models import ClientCompany, CompanyInformer, JiraIssue, Client
from app.schemas import ClientCompanyCreate, CompanyInformerCreate, VisitTicketCreate
import app.routers.api as api_router


def test_client_companies_crud_and_ticket_creation():
    # 1. Setup in-memory SQLite DB
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    # 2. Test ClientCompany creation
    company_payload = ClientCompanyCreate(name="Acme Corp")
    company = api_router.create_client_company(company_payload, db=db)
    assert company.id is not None
    assert company.name == "Acme Corp"
    
    # Test duplicate prevention
    try:
        api_router.create_client_company(company_payload, db=db)
        assert False, "Should raise exception on duplicate company"
    except HTTPException as e:
        assert e.status_code == 400
        
    # 3. Test CompanyInformer creation
    informer_payload = CompanyInformerCreate(
        name="John Doe",
        email="john@acme.com",
        jira_account_id="jira-user-john"
    )
    informer = api_router.create_company_informer(company.id, informer_payload, db=db)
    assert informer.id is not None
    assert informer.name == "John Doe"
    assert informer.company_id == company.id
    
    # Test listing companies
    companies = api_router.list_client_companies(db=db)
    assert len(companies) == 1
    assert companies[0].name == "Acme Corp"
    assert len(companies[0].informers) == 1
    assert companies[0].informers[0].name == "John Doe"
    
    # 4. Test populate_from_history
    # Let's add a dummy reporter Client, a dummy Agent, and a JiraIssue to simulate history
    reporter_client = Client(jira_account_id="jira-reporter-1", name="Alice Smith", email="alice@test.com")
    db.add(reporter_client)
    db.flush()
    
    # Create issue with raw_payload having client_text (customfield_10495)
    issue = JiraIssue(
        jira_id="issue-1",
        jira_key="MABC-1",
        summary="Test Issue",
        project_key="MABC",
        issue_type="Incident",
        status="Open",
        raw_payload={"fields": {"customfield_10495": "History Client"}},
        reporter_client_id=reporter_client.id
    )
    db.add(issue)
    db.commit()
    
    # Call populate
    pop_res = api_router.populate_from_history(db=db)
    assert pop_res["companies_added"] == 1
    assert pop_res["informers_added"] == 1
    
    # Check populated company
    history_company = db.query(ClientCompany).filter_by(name="History Client").first()
    assert history_company is not None
    assert len(history_company.informers) == 1
    assert history_company.informers[0].name == "Alice Smith"
    
    # 5. Test create_visit_ticket
    # Mock JIRA Client and Sync function
    with patch("app.services.jira.JiraClient") as mock_jira_class, \
         patch("app.services.sync.sync_single_issue_by_key") as mock_sync_func:
         
        mock_jira_instance = MagicMock()
        mock_jira_class.return_value = mock_jira_instance
        mock_jira_instance.create_issue.return_value = {"id": "10001", "key": "MABC-99"}
        
        # Test creation schema payload
        visit_payload = VisitTicketCreate(
            company_id=company.id,
            informer_id=informer.id,
            assignee_account_id="jira-agent-bob",
            start_date=datetime(2026, 7, 10, 14, 30),
            end_date=datetime(2026, 7, 10, 17, 30),
            service_level="L2",
            ticket_category="Estaciones de Trabajo",
            description="Reunión mensual de coordinación"
        )
        
        visit_res = api_router.create_visit_ticket(visit_payload, db=db)
        assert visit_res["status"] == "ok"
        assert visit_res["key"] == "MABC-99"
        
        # Verify JIRA Client was called
        mock_jira_instance.create_issue.assert_called_once()
        mock_sync_func.assert_called_once_with(db, "MABC-99")
        
    db.close()
