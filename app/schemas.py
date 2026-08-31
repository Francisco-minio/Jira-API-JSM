from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ClientCreate(BaseModel):
    jira_account_id: str | None = None
    name: str
    email: str | None = None
    active: bool = True


class AgentCreate(BaseModel):
    jira_account_id: str | None = None
    name: str
    email: str | None = None
    active: bool = True


class SyncResponse(BaseModel):
    issues_seen: int
    issues_upserted: int
    worklogs_upserted: int


class ReportFilters(BaseModel):
    from_date: date
    to_date: date


class SeriesPoint(BaseModel):
    label: str
    value: float


class AgentReportRow(BaseModel):
    agent_id: int
    agent_name: str
    hours_logged: float
    capacity_hours: float
    utilization_pct: float
    incidents: int
    clients: int


class ClientReportRow(BaseModel):
    client_id: int
    client_name: str
    client_email: str | None = None
    tickets_registered: int
    tickets_attended: int
    hours_logged: float
    incidents: int


class TicketWorklogRow(BaseModel):
    worklog_id: str
    started_at: datetime | None = None
    author_name: str | None = None
    hours: float
    comment: str | None = None


class ClientTicketRow(BaseModel):
    issue_id: int
    jira_key: str
    organizations: list[str] | None = None
    client_text: str | None = None
    service_level: str | None = None
    summary: str
    status: str
    assignee_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    hours_logged: float
    worklog_count: int
    incident: bool
    worklogs: list[TicketWorklogRow]



class ClientDetailReport(BaseModel):
    client_id: int
    client_name: str
    client_email: str | None = None
    period_from: date
    period_to: date
    tickets_registered: int
    tickets_attended: int
    tickets_with_hours: int
    hours_logged: float
    incident_count: int
    tickets: list[ClientTicketRow]


class AgentResponse(BaseModel):
    id: int
    jira_account_id: str | None = None
    name: str
    email: str | None = None
    active: bool

    class Config:
        from_attributes = True


class ClientResponse(BaseModel):
    id: int
    jira_account_id: str | None = None
    name: str
    email: str | None = None
    active: bool

    class Config:
        from_attributes = True


class OrganizationResponse(BaseModel):
    id: int
    jira_organization_id: str | None = None
    name: str
    active: bool

    class Config:
        from_attributes = True


class OverviewPeriod(BaseModel):
    from_: date = None
    to: date = None
    
    # We alias from_ to from to handle python reserved keyword.
    class Config:
        populate_by_name = True
        alias_generator = lambda string: "from" if string == "from_" else string


class OverviewReport(BaseModel):
    period: OverviewPeriod
    hours_logged: float
    expected_capacity_hours: float
    utilization_pct: float
    incidents: int
    business_days: int


class TopTicketRow(BaseModel):
    jira_key: str
    summary: str
    client_text: str | None = None
    service_level: str | None = None
    hours_logged: float
    worklog_count: int


class WeeklyReportRow(BaseModel):
    week_start: date
    week_end: date
    period_from: date
    period_to: date
    label: str
    business_days: int
    hours_logged: float
    hours_l1_l2: float = 0.0
    hours_l3: float = 0.0
    expected_capacity_hours: float
    utilization_pct: float
    tickets_registered: int
    tickets_attended: int
    incidents: int
    holiday_names: list[str]
    top_client: str | None = None
    top_agent: str | None = None
    summary: str
    top_tickets: list[TopTicketRow]


class OrganizationReportRow(BaseModel):
    organization_id: int
    organization_name: str
    tickets_registered: int
    tickets_attended: int
    hours_logged: float
    incidents: int


class OrganizationDetailReport(BaseModel):
    organization_id: int
    organization_name: str
    client_filter: str | None = None
    period_from: date
    period_to: date
    tickets_registered: int
    tickets_attended: int
    tickets_with_hours: int
    hours_logged: float
    incident_count: int
    tickets: list[ClientTicketRow]


class TicketClientOption(BaseModel):
    client_text: str
    client_key: str
    tickets: int
    hours_logged: float
    incidents: int


class ServiceLevelRow(BaseModel):
    service_level: str
    tickets_registered: int
    tickets_attended: int
    hours_logged: float
    incidents: int


class TicketClientDetailReport(BaseModel):
    client_text: str
    client_key: str
    period_from: date
    period_to: date
    tickets_registered: int
    tickets_attended: int
    tickets_with_hours: int
    hours_logged: float
    incident_count: int
    tickets: list[ClientTicketRow]


class AgentDetailReport(BaseModel):
    agent_id: int
    agent_name: str
    agent_email: str | None = None
    period_from: date
    period_to: date
    tickets_assigned: int
    tickets_attended: int
    tickets_with_hours: int
    hours_logged: float
    capacity_hours: float
    utilization_pct: float
    incident_count: int
    tickets: list[ClientTicketRow]


class SettingsUpdateSchema(BaseModel):
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_jql: str
    jira_organization_field_id: str
    jira_client_field_id: str
    jira_service_level_field_id: str
    jira_project_key: str
    jira_tipo_atencion_field_id: str
    jira_categoria_ticket_field_id: str
    jira_fecha_inicio_field_id: str
    weekly_hours: int
    daily_hours: int
    sync_interval_hours: int
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    email_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str


class TelegramTestSchema(BaseModel):
    telegram_bot_token: str
    telegram_chat_id: str


class EmailTestSchema(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str


class CompanyInformerResponse(BaseModel):
    id: int
    company_id: int
    name: str
    email: str | None = None
    jira_account_id: str | None = None
    active: bool

    class Config:
        from_attributes = True


class ClientCompanyResponse(BaseModel):
    id: int
    name: str
    active: bool
    informers: list[CompanyInformerResponse] | None = None

    class Config:
        from_attributes = True


class ClientCompanyCreate(BaseModel):
    name: str


class CompanyInformerCreate(BaseModel):
    name: str
    email: str | None = None
    jira_account_id: str | None = None


class VisitTicketCreate(BaseModel):
    company_id: int
    informer_id: int
    assignee_account_id: str
    start_date: datetime
    end_date: datetime
    service_level: str
    ticket_category: str | None = None
    description: str | None = None


class VisitTicketUpdate(BaseModel):
    start_date: datetime
    end_date: datetime
    assignee_account_id: str | None = None
    description: str | None = None
    service_level: str | None = None
    ticket_category: str | None = None


class HoursConsumptionKPI(BaseModel):
    total_hours: float
    total_worklogs: int
    total_tickets: int
    avg_hours_per_ticket: float
    top_client_name: str | None = None
    top_client_hours: float = 0.0
    top_agent_name: str | None = None
    top_agent_hours: float = 0.0


class HoursConsumptionClientRow(BaseModel):
    client_name: str
    hours_logged: float
    ticket_count: int
    percentage: float


class HoursConsumptionAgentRow(BaseModel):
    agent_id: int | None = None
    agent_name: str
    hours_logged: float
    ticket_count: int
    percentage: float


class HoursConsumptionServiceLevelRow(BaseModel):
    service_level: str
    hours_logged: float
    ticket_count: int
    percentage: float


class HoursConsumptionTicketRow(BaseModel):
    jira_key: str
    summary: str
    client_name: str
    agent_name: str
    service_level: str
    hours_logged: float
    worklog_count: int


class HoursConsumptionSeriesPoint(BaseModel):
    date: str
    hours: float


class HoursConsumptionStatusRow(BaseModel):
    status_name: str
    hours_logged: float
    ticket_count: int
    percentage: float


class HoursConsumptionReport(BaseModel):
    start_date: str
    end_date: str
    kpis: HoursConsumptionKPI
    clients: list[HoursConsumptionClientRow]
    agents: list[HoursConsumptionAgentRow]
    service_levels: list[HoursConsumptionServiceLevelRow]
    statuses: list[HoursConsumptionStatusRow]
    tickets: list[HoursConsumptionTicketRow]
    daily_series: list[HoursConsumptionSeriesPoint]


class VisitsReportKPI(BaseModel):
    total_visits: int
    scheduled_visits: int
    unscheduled_visits: int
    total_hours: float
    avg_hours_per_visit: float
    top_client_name: str | None = None
    top_client_visits: int = 0


class VisitsReportTypeRow(BaseModel):
    visit_type: str
    visit_count: int
    hours_logged: float
    percentage: float


class VisitsReportClientRow(BaseModel):
    client_name: str
    scheduled_count: int
    unscheduled_count: int
    total_visits: int
    hours_logged: float


class VisitsReportAgentRow(BaseModel):
    agent_id: int | None = None
    agent_name: str
    scheduled_count: int
    unscheduled_count: int
    total_visits: int
    hours_logged: float


class VisitsReportTicketRow(BaseModel):
    jira_key: str
    summary: str
    client_name: str
    agent_name: str
    visit_type: str
    visit_date: str
    hours_logged: float
    status: str


class VisitsReportSeriesPoint(BaseModel):
    date: str
    scheduled_count: int
    unscheduled_count: int
    total_visits: int


class VisitsReport(BaseModel):
    start_date: str
    end_date: str
    kpis: VisitsReportKPI
    types: list[VisitsReportTypeRow]
    clients: list[VisitsReportClientRow]
    agents: list[VisitsReportAgentRow]
    tickets: list[VisitsReportTicketRow]
    daily_series: list[VisitsReportSeriesPoint]
