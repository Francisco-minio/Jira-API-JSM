from unittest.mock import patch, MagicMock
from fastapi import Request
from app.schemas import SettingsUpdateSchema
import app.routers.web as web_router
import app.routers.api as api_router

def test_get_configuration():
    mock_request = MagicMock(spec=Request)
    mock_request.app = MagicMock()
    mock_request.app.title = "Jira Report"
    
    response = web_router.configuration(mock_request)
    assert response.template.name == "configuration.html"
    assert "settings" in response.context

@patch("app.services.jira.JiraClient")
def test_test_connection_success(mock_jira_client):
    # Setup mock instance
    mock_instance = MagicMock()
    mock_jira_client.return_value = mock_instance
    mock_instance.search_issues.return_value = []
    
    payload = SettingsUpdateSchema(
        jira_base_url="https://test.atlassian.net",
        jira_email="test@example.com",
        jira_api_token="token",
        jira_jql="project = HD",
        jira_organization_field_id="customfield_10002",
        jira_client_field_id="customfield_10495",
        jira_service_level_field_id="customfield_10528",
        jira_project_key="MABC",
        jira_tipo_atencion_field_id="customfield_10561",
        jira_categoria_ticket_field_id="customfield_10396",
        jira_fecha_inicio_field_id="customfield_10015",
        weekly_hours=40,
        daily_hours=8,
        sync_interval_hours=2,
        telegram_enabled=False,
        telegram_bot_token="",
        telegram_chat_id="",
        email_enabled=False,
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        email_from="",
        email_to=""
    )
    
    response = api_router.test_connection(payload)
    assert response == {"status": "ok"}
    mock_jira_client.assert_called_once_with("https://test.atlassian.net", "test@example.com", "token")
    mock_instance.search_issues.assert_called_once_with("project = HD", max_results=1)

@patch("app.services.jira.JiraClient")
def test_test_connection_error(mock_jira_client):
    from fastapi import HTTPException
    # Setup mock instance to raise exception
    mock_instance = MagicMock()
    mock_jira_client.return_value = mock_instance
    mock_instance.search_issues.side_effect = Exception("Connection refused")
    
    payload = SettingsUpdateSchema(
        jira_base_url="https://test.atlassian.net",
        jira_email="test@example.com",
        jira_api_token="token",
        jira_jql="project = HD",
        jira_organization_field_id="customfield_10002",
        jira_client_field_id="customfield_10495",
        jira_service_level_field_id="customfield_10528",
        jira_project_key="MABC",
        jira_tipo_atencion_field_id="customfield_10561",
        jira_categoria_ticket_field_id="customfield_10396",
        jira_fecha_inicio_field_id="customfield_10015",
        weekly_hours=40,
        daily_hours=8,
        sync_interval_hours=2,
        telegram_enabled=False,
        telegram_bot_token="",
        telegram_chat_id="",
        email_enabled=False,
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        email_from="",
        email_to=""
    )
    
    try:
        api_router.test_connection(payload)
        assert False, "Should have raised HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Connection refused" in exc.detail

@patch("os.path.exists")
@patch("builtins.open")
@patch("os.utime")
def test_update_settings(mock_utime, mock_open, mock_exists):
    # Mocking environment check and file operations
    mock_exists.return_value = True
    
    # We will simulate reading a basic .env file
    mock_file = MagicMock()
    mock_file.readlines.return_value = [
        "JIRA_BASE_URL=https://old.atlassian.net\n",
        "JIRA_EMAIL=old@example.com\n"
    ]
    mock_open.return_value.__enter__.return_value = mock_file
    
    payload = SettingsUpdateSchema(
        jira_base_url="https://new.atlassian.net",
        jira_email="new@example.com",
        jira_api_token="newtoken",
        jira_jql="project = NEW",
        jira_organization_field_id="customfield_99999",
        jira_client_field_id="customfield_88888",
        jira_service_level_field_id="customfield_77777",
        jira_project_key="NEW",
        jira_tipo_atencion_field_id="customfield_66666",
        jira_categoria_ticket_field_id="customfield_55555",
        jira_fecha_inicio_field_id="customfield_44444",
        weekly_hours=45,
        daily_hours=9,
        sync_interval_hours=4,
        telegram_enabled=False,
        telegram_bot_token="",
        telegram_chat_id="",
        email_enabled=False,
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        email_from="",
        email_to=""
    )
    
    response = api_router.update_settings(payload)
    assert response == {"status": "ok"}
    
    # Assert that write was called
    mock_open.assert_any_call(".env", "w", encoding="utf-8")
    mock_utime.assert_called_once_with("app/main.py", None)
