from datetime import date

from app.models import JiraIssue
from app.services.calendar import expected_capacity_hours
from app.services.reports import _issue_service_level_label, get_settings


def test_expected_capacity_hours_uses_business_days():
    capacity = expected_capacity_hours(date(2026, 5, 4), date(2026, 5, 8), 8)
    assert capacity == 40.0


def test_issue_service_level_label_groups_l1_l2():
    settings = get_settings()
    settings_field = settings.jira_service_level_field_id
    
    issue_l1 = JiraIssue(raw_payload={"fields": {settings_field: "L1"}})
    issue_l2 = JiraIssue(raw_payload={"fields": {settings_field: "  l2  "}})
    issue_l3 = JiraIssue(raw_payload={"fields": {settings_field: "L3"}})
    issue_none = JiraIssue(raw_payload={"fields": {}})
    
    assert _issue_service_level_label(issue_l1) == "L1/L2"
    assert _issue_service_level_label(issue_l2) == "L1/L2"
    assert _issue_service_level_label(issue_l3) == "L3"
    assert _issue_service_level_label(issue_none) == "Sin nivel"

