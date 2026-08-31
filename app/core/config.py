from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Jira Helpdesk Report"
    app_timezone: str = "America/Santiago"
    database_url: str = "sqlite:///./jira_report.db"

    # Seguridad y Autenticación
    secret_key: str = "jira-report-secret-key-prod-change-me-please-998877"
    admin_username: str = "admin"
    admin_password: str = "admin1234"
    session_cookie_name: str = "jira_session_token"
    session_max_age_seconds: int = 604800  # 7 días

    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_jql: str = "project = HD ORDER BY updated DESC"
    jira_organization_field_id: str = "customfield_10002"
    jira_client_field_id: str = "customfield_10495"
    jira_service_level_field_id: str = "customfield_10528"
    jira_project_key: str = "MABC"
    jira_tipo_atencion_field_id: str = "customfield_10561"
    jira_categoria_ticket_field_id: str = "customfield_10396"
    jira_fecha_inicio_field_id: str = "customfield_10015"

    weekly_hours: int = 40
    daily_hours: int = 8
    sync_page_size: int = 50
    sync_max_issues: int = 5000
    sync_interval_hours: int = 2

    # Notificaciones Telegram
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Notificaciones Correo (SMTP)
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
