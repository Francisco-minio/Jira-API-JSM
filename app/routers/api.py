from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db import SessionLocal
from app.schemas import (
    AgentCreate, ClientCreate, SyncResponse, AgentResponse, ClientResponse,
    OrganizationResponse, OverviewReport, SeriesPoint, WeeklyReportRow, AgentReportRow,
    ClientReportRow, ClientDetailReport, OrganizationReportRow, OrganizationDetailReport,
    TicketClientOption, ServiceLevelRow, TicketClientDetailReport, ClientTicketRow,
    AgentDetailReport, SettingsUpdateSchema, TelegramTestSchema, EmailTestSchema,
    ClientCompanyResponse, ClientCompanyCreate, CompanyInformerCreate, CompanyInformerResponse,
    VisitTicketCreate, VisitTicketUpdate, HoursConsumptionReport, VisitsReport
)
from app.services.reports import (
    build_agent_report,
    build_client_detail,
    build_client_report,
    build_organization_detail,
    build_organization_report,
    build_service_level_report,
    build_weekly_report,
    build_ticket_client_detail,
    build_ticket_client_options,
    build_daily_series,
    build_monthly_series,
    build_overview,
    build_tickets_report,
    build_agent_detail,
    build_clients_export_data,
    build_hours_consumption_report,
    get_distinct_issue_statuses,
    build_visits_report,
)
from app.services.pdf_report import generate_hours_consumption_pdf, generate_visits_report_pdf
from app.services.sync import sync_from_jira, sync_single_issue_by_key
from app.models import Agent, Client, Organization, ClientCompany, CompanyInformer, JiraIssue
from sqlalchemy import select, and_


router = APIRouter(prefix="/api", tags=["api"])
settings = get_settings()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@router.post("/sync", response_model=SyncResponse)
def sync(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    result = None
    error = None
    try:
        result = sync_from_jira(db, from_date=from_date, to_date=to_date)
        return result
    except RuntimeError as exc:
        error = exc
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        try:
            from app.services.notifications import notify_sync_result
            notify_sync_result(result, error)
        except Exception as ne:
            import logging
            logger_err = logging.getLogger("uvicorn.error")
            logger_err.error(f"Error al enviar notificaciones de sincronización manual: {ne}")


@router.post("/clients", response_model=ClientResponse)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    client = Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.post("/agents", response_model=AgentResponse)
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    agent = Agent(**payload.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/agents", response_model=list[AgentResponse])
def list_agents(db: Session = Depends(get_db)):
    return db.scalars(select(Agent).order_by(Agent.name)).all()


@router.get("/clients", response_model=list[ClientResponse])
def list_clients(db: Session = Depends(get_db)):
    return db.scalars(select(Client).order_by(Client.name)).all()


@router.get("/clients/export")
def export_clients(
    format: str = Query("csv"),
    db: Session = Depends(get_db),
):
    data = build_clients_export_data(db)
    if format.lower() == "json":
        return data

    import csv
    import io

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Microsoft Excel compatibility
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "ID Cliente",
        "Nombre / Informador",
        "Correo Electrónico",
        "Empresa / Organización",
        "Tickets Reportados",
        "ID Cuenta Jira",
        "Estado",
    ])

    for row in data:
        writer.writerow([
            row["id"],
            row["name"],
            row["email"],
            row["company"],
            row["ticket_count"],
            row["jira_account_id"],
            row["active"],
        ])

    csv_text = output.getvalue()
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=clientes_y_correos.csv"
        },
    )



@router.get("/organizations", response_model=list[OrganizationResponse])
def list_organizations(db: Session = Depends(get_db)):
    return db.scalars(select(Organization).where(Organization.active.is_(True)).order_by(Organization.name)).all()


@router.get("/reports/overview", response_model=OverviewReport)
def reports_overview(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_overview(db, from_date, to_date, client_text=client_text)


@router.get("/reports/daily", response_model=list[SeriesPoint])
def reports_daily(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_daily_series(db, from_date, to_date, client_text=client_text)


@router.get("/reports/monthly", response_model=list[SeriesPoint])
def reports_monthly(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_monthly_series(db, from_date, to_date, client_text=client_text)


@router.get("/reports/weekly", response_model=list[WeeklyReportRow])
def reports_weekly(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_weekly_report(db, from_date, to_date, client_text=client_text)


@router.get("/reports/agents", response_model=list[AgentReportRow])
def reports_agents(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_agent_report(db, from_date, to_date, client_text=client_text)


@router.get("/reports/agents/{agent_id}", response_model=AgentDetailReport)
def reports_agent_detail(
    agent_id: int,
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
):
    return build_agent_detail(db, agent_id, from_date, to_date)


@router.get("/reports/clients", response_model=list[ClientReportRow])
def reports_clients(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
):
    return build_client_report(db, from_date, to_date)


@router.get("/reports/clients/{client_id}", response_model=ClientDetailReport)
def reports_client_detail(
    client_id: int,
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
):
    return build_client_detail(db, client_id, from_date, to_date)


@router.get("/reports/organizations", response_model=list[OrganizationReportRow])
def reports_organizations(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_organization_report(db, from_date, to_date, client_text=client_text)


@router.get("/reports/organizations/{organization_id}", response_model=OrganizationDetailReport)
def reports_organization_detail(
    organization_id: int,
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_organization_detail(db, organization_id, from_date, to_date, client_text=client_text)


@router.get("/reports/ticket-clients", response_model=list[TicketClientOption])
def reports_ticket_clients(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
):
    return build_ticket_client_options(db, from_date, to_date)


@router.get("/reports/service-levels", response_model=list[ServiceLevelRow])
def reports_service_levels(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_service_level_report(db, from_date, to_date, client_text=client_text)


@router.get("/reports/ticket-clients/detail", response_model=TicketClientDetailReport)
def reports_ticket_client_detail(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str = Query(...),
    db: Session = Depends(get_db),
):
    return build_ticket_client_detail(db, client_text, from_date, to_date)


@router.get("/reports/tickets", response_model=list[ClientTicketRow])
def reports_tickets(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    status: str | None = Query(None),
    service_level: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_tickets_report(
        db, 
        from_date, 
        to_date, 
        client_text=client_text, 
        status=status, 
        service_level=service_level
    )


@router.get("/reports/statuses", response_model=list[str])
def reports_statuses(db: Session = Depends(get_db)):
    return get_distinct_issue_statuses(db)


@router.get("/reports/hours-consumption", response_model=HoursConsumptionReport)
def reports_hours_consumption(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    agent_id: int | None = Query(None),
    service_level: str | None = Query(None),
    statuses: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_hours_consumption_report(
        db,
        from_date,
        to_date,
        client_text=client_text,
        agent_id=agent_id,
        service_level=service_level,
        statuses=statuses,
    )


@router.get("/reports/hours-consumption/pdf")
def reports_hours_consumption_pdf(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    agent_id: int | None = Query(None),
    service_level: str | None = Query(None),
    statuses: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    report_data = build_hours_consumption_report(
        db,
        from_date,
        to_date,
        client_text=client_text,
        agent_id=agent_id,
        service_level=service_level,
        statuses=statuses,
    )
    client_label = client_text if (client_text and client_text.strip()) else "Todos los clientes"
    agent_label = "Todos los agentes"
    if agent_id:
        agent_obj = db.get(Agent, agent_id)
        if agent_obj:
            agent_label = agent_obj.name

    status_label = ", ".join(statuses) if statuses else "Todos los estados"

    pdf_bytes = generate_hours_consumption_pdf(
        report_data,
        client_filter_label=client_label,
        agent_filter_label=agent_label,
        status_filter_label=status_label,
    )
    filename = f"Reporte_Ejecutivo_Consumo_Horas_{from_date}_{to_date}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/reports/visits", response_model=VisitsReport)
def reports_visits(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    agent_id: int | None = Query(None),
    visit_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return build_visits_report(
        db,
        from_date,
        to_date,
        client_text=client_text,
        agent_id=agent_id,
        visit_type=visit_type,
    )


@router.get("/reports/visits/pdf")
def reports_visits_pdf(
    from_date: date = Query(...),
    to_date: date = Query(...),
    client_text: str | None = Query(None),
    agent_id: int | None = Query(None),
    visit_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    report_data = build_visits_report(
        db,
        from_date,
        to_date,
        client_text=client_text,
        agent_id=agent_id,
        visit_type=visit_type,
    )
    client_label = client_text if (client_text and client_text.strip()) else "Todos los clientes"
    agent_label = "Todos los agentes"
    if agent_id:
        agent_obj = db.get(Agent, agent_id)
        if agent_obj:
            agent_label = agent_obj.name

    vt_label = visit_type if (visit_type and visit_type.strip()) else "Todas las visitas"

    pdf_bytes = generate_visits_report_pdf(
        report_data,
        client_filter_label=client_label,
        agent_filter_label=agent_label,
        visit_type_filter_label=vt_label,
    )
    filename = f"Reporte_Ejecutivo_Visitas_{from_date}_{to_date}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/settings/test-connection")
def test_connection(payload: SettingsUpdateSchema):
    import requests
    from app.services.jira import JiraClient
    try:
        client = JiraClient(payload.jira_base_url, payload.jira_email, payload.jira_api_token)
        # Ejecutamos una búsqueda sencilla de prueba (maxResults=1)
        client.search_issues(payload.jira_jql, max_results=1)
        return {"status": "ok"}
    except Exception as e:
        detail = str(e)
        if isinstance(e, requests.exceptions.HTTPError):
            if e.response.status_code == 401:
                detail = "Credenciales incorrectas de Jira (Unauthorized 401)."
            elif e.response.status_code == 404:
                detail = "Dirección URL base de Jira no encontrada (404)."
            else:
                detail = f"Error de Jira API (Status {e.response.status_code}): {e.response.text}"
        raise HTTPException(status_code=400, detail=detail)


@router.post("/settings")
def update_settings(payload: SettingsUpdateSchema):
    import os
    env_path = ".env"
    
    new_values = {
        "JIRA_BASE_URL": payload.jira_base_url,
        "JIRA_EMAIL": payload.jira_email,
        "JIRA_API_TOKEN": payload.jira_api_token,
        "JIRA_JQL": payload.jira_jql,
        "JIRA_ORGANIZATION_FIELD_ID": payload.jira_organization_field_id,
        "JIRA_CLIENT_FIELD_ID": payload.jira_client_field_id,
        "JIRA_SERVICE_LEVEL_FIELD_ID": payload.jira_service_level_field_id,
        "JIRA_PROJECT_KEY": payload.jira_project_key,
        "JIRA_TIPO_ATENCION_FIELD_ID": payload.jira_tipo_atencion_field_id,
        "JIRA_CATEGORIA_TICKET_FIELD_ID": payload.jira_categoria_ticket_field_id,
        "JIRA_FECHA_INICIO_FIELD_ID": payload.jira_fecha_inicio_field_id,
        "WEEKLY_HOURS": str(payload.weekly_hours),
        "DAILY_HOURS": str(payload.daily_hours),
        "SYNC_INTERVAL_HOURS": str(payload.sync_interval_hours),
        "TELEGRAM_ENABLED": "True" if payload.telegram_enabled else "False",
        "TELEGRAM_BOT_TOKEN": payload.telegram_bot_token,
        "TELEGRAM_CHAT_ID": payload.telegram_chat_id,
        "EMAIL_ENABLED": "True" if payload.email_enabled else "False",
        "SMTP_HOST": payload.smtp_host,
        "SMTP_PORT": str(payload.smtp_port),
        "SMTP_USER": payload.smtp_user,
        "SMTP_PASSWORD": payload.smtp_password,
        "EMAIL_FROM": payload.email_from,
        "EMAIL_TO": payload.email_to,
    }

    try:
        # Crear archivo .env si no existe
        if not os.path.exists(env_path):
            with open(env_path, "w", encoding="utf-8") as f:
                pass

        # Leer archivo existente
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated_keys = set()
        new_lines = []

        for line in lines:
            stripped = line.strip()
            # Conservar líneas en blanco y comentarios intactos
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            parts = stripped.split("=", 1)
            key = parts[0].strip()
            if key in new_values:
                new_lines.append(f"{key}={new_values[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)

        # Añadir llaves faltantes
        for key, val in new_values.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={val}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        # Tocar app/main.py para gatillar la recarga automática de Uvicorn
        main_py_path = "app/main.py"
        if os.path.exists(main_py_path):
            os.utime(main_py_path, None)

        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al escribir archivo .env: {str(e)}")


@router.post("/settings/test-telegram")
def test_telegram(payload: TelegramTestSchema):
    from app.services.notifications import send_telegram_message
    try:
        send_telegram_message(
            payload.telegram_bot_token,
            payload.telegram_chat_id,
            "🔔 <b>Mensaje de prueba</b> del Dashboard de Reportes de Jira. ¡La integración funciona correctamente!"
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al enviar por Telegram: {str(e)}")


@router.post("/settings/test-email")
def test_email(payload: EmailTestSchema):
    from app.services.notifications import send_email_message
    try:
        subject = "🔔 [Jira Report] Correo de Prueba"
        html_body = """
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f9f9f9; padding: 20px; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #e1e1e1; border-radius: 8px; padding: 24px;">
                <h2 style="color: #0ea5e9; margin-top: 0;">🔔 Correo de Prueba</h2>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 16px 0;" />
                <p>Si has recibido este mensaje, significa que la configuración de SMTP en el Dashboard de Reportes de Jira es correcta.</p>
                <p style="font-size: 0.85em; color: #666; margin-top: 24px;">
                    Enviado automáticamente por el sistema de reportes.
                </p>
            </div>
        </body>
        </html>
        """
        send_email_message(
            payload.smtp_host,
            payload.smtp_port,
            payload.smtp_user,
            payload.smtp_password,
            payload.email_from,
            payload.email_to,
            subject,
            html_body
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al enviar correo (SMTP): {str(e)}")


# API CRUD Clientes y Visitas

@router.get("/client-companies", response_model=list[ClientCompanyResponse])
def list_client_companies(db: Session = Depends(get_db)):
    stmt = select(ClientCompany).options(selectinload(ClientCompany.informers)).order_by(ClientCompany.name)
    return db.scalars(stmt).all()


@router.post("/client-companies", response_model=ClientCompanyResponse)
def create_client_company(payload: ClientCompanyCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(ClientCompany).where(ClientCompany.name == payload.name))
    if existing:
        raise HTTPException(status_code=400, detail="La empresa ya existe.")
    company = ClientCompany(name=payload.name, active=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.delete("/client-companies/{company_id}")
def delete_client_company(company_id: int, db: Session = Depends(get_db)):
    company = db.get(ClientCompany, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    db.delete(company)
    db.commit()
    return {"status": "ok"}


@router.post("/client-companies/{company_id}/informers", response_model=CompanyInformerResponse)
def create_company_informer(company_id: int, payload: CompanyInformerCreate, db: Session = Depends(get_db)):
    company = db.get(ClientCompany, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    
    informer = CompanyInformer(
        company_id=company_id,
        name=payload.name,
        email=payload.email,
        jira_account_id=payload.jira_account_id,
        active=True
    )
    db.add(informer)
    db.commit()
    db.refresh(informer)
    return informer


@router.delete("/client-companies/informers/{informer_id}")
def delete_company_informer(informer_id: int, db: Session = Depends(get_db)):
    informer = db.get(CompanyInformer, informer_id)
    if not informer:
        raise HTTPException(status_code=404, detail="Informador no encontrado.")
    db.delete(informer)
    db.commit()
    return {"status": "ok"}


@router.post("/client-companies/populate")
def populate_from_history(db: Session = Depends(get_db)):
    from app.services.reports import _extract_client_text
    
    stmt = select(JiraIssue).where(JiraIssue.reporter_client_id.is_not(None))
    issues = db.scalars(stmt).all()
    
    count_companies = 0
    count_informers = 0
    
    for issue in issues:
        client_text = _extract_client_text(issue)
        if not client_text:
            continue
        
        company = db.scalar(select(ClientCompany).where(ClientCompany.name == client_text))
        if not company:
            company = ClientCompany(name=client_text, active=True)
            db.add(company)
            db.flush()
            count_companies += 1
            
        reporter = issue.reporter_client
        if reporter:
            informer = db.scalar(select(CompanyInformer).where(
                and_(
                    CompanyInformer.company_id == company.id,
                    CompanyInformer.jira_account_id == reporter.jira_account_id
                )
            ))
            if not informer:
                informer = CompanyInformer(
                    company_id=company.id,
                    name=reporter.name,
                    email=reporter.email,
                    jira_account_id=reporter.jira_account_id,
                    active=True
                )
                db.add(informer)
                db.flush()
                count_informers += 1
                
    db.commit()
    return {"status": "ok", "companies_added": count_companies, "informers_added": count_informers}


@router.post("/tickets/create-visit")
def create_visit_ticket(payload: VisitTicketCreate, db: Session = Depends(get_db)):
    from app.services.jira import JiraClient
    from app.services.sync import sync_single_issue_by_key
    
    company = db.get(ClientCompany, payload.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    informer = db.get(CompanyInformer, payload.informer_id)
    if not informer:
        raise HTTPException(status_code=404, detail="Informador no encontrado.")
    
    # Fetch agent name
    agent = db.scalar(select(Agent).where(Agent.jira_account_id == payload.assignee_account_id))
    agent_name = agent.name if agent else "No asignado"
    
    from zoneinfo import ZoneInfo
    app_tz = ZoneInfo(settings.app_timezone)
    start_local = payload.start_date.astimezone(app_tz)
    end_local = payload.end_date.astimezone(app_tz)
    
    date_str = start_local.strftime("%d-%m-%Y")
    start_str = start_local.strftime("%d/%m/%Y %H:%M")
    end_str = end_local.strftime("%d/%m/%Y %H:%M")
    
    summary = f"Visita {date_str} {company.name.upper()}"
    
    # 1. Build ADF description
    adf_content = [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Profesional Asignado: "},
                {"type": "text", "text": agent_name, "marks": [{"type": "strong"}]}
            ]
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Cliente: "},
                {"type": "text", "text": company.name.upper(), "marks": [{"type": "strong"}]}
            ]
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Inicio: "},
                {"type": "text", "text": start_str}
            ]
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Término: "},
                {"type": "text", "text": end_str}
            ]
        }
    ]
    
    if payload.description:
        # Add a blank line
        adf_content.append({"type": "paragraph", "content": []})
        adf_content.append({
            "type": "paragraph",
            "content": [
                {"type": "text", "text": payload.description}
            ]
        })
        
    adf_description = {
        "type": "doc",
        "version": 1,
        "content": adf_content
    }
    
    # 2. Build JIRA fields
    jira_fields = {
        "project": {"key": settings.jira_project_key},
        "summary": summary,
        "description": adf_description,
        "issuetype": {"id": "10146"},
        "reporter": {"accountId": informer.jira_account_id} if informer.jira_account_id else None,
        "assignee": {"accountId": payload.assignee_account_id} if payload.assignee_account_id else None,
        settings.jira_client_field_id: company.name,
        settings.jira_service_level_field_id: {"value": "L2" if payload.service_level == "L1/L2" else payload.service_level},
        settings.jira_tipo_atencion_field_id: {"id": "10406"},
        settings.jira_categoria_ticket_field_id: [{"value": payload.ticket_category}] if payload.ticket_category else None,
        settings.jira_fecha_inicio_field_id: start_local.strftime("%Y-%m-%d"),
        "duedate": end_local.strftime("%Y-%m-%d"),
    }
    
    jira_fields = {k: v for k, v in jira_fields.items() if v is not None}
    
    # 3. Build update comment block
    jira_update = {
        "comment": [
            {
                "add": {
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"\"Este campo debes tomarlo del nombre del tecnico asignado: {agent_name}\""
                                    }
                                ]
                            },
                            {
                                "type": "bulletList",
                                "content": [
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [
                                                    {
                                                        "type": "text",
                                                        "text": "Recuerde describir de manera clara todas aquellas actividades que realizó durante su visita."
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [
                                                    {
                                                        "type": "text",
                                                        "text": "Registre el tiempo total que utilizó para su visita."
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [
                                                    {
                                                        "type": "text",
                                                        "text": "Actualice el estado del ticket."
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Saludos."
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        ]
    }
    
    try:
        jira = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
        issue_res = jira.create_issue(jira_fields, update=jira_update)
        new_key = issue_res.get("key")
        
        if new_key:
            sync_single_issue_by_key(db, new_key)
            
        return {"status": "ok", "key": new_key}
    except Exception as e:
        detail = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                err_data = e.response.json()
                if "errors" in err_data:
                    detail = f"JIRA Errors: {err_data['errors']}"
                elif "errorMessages" in err_data:
                    detail = f"JIRA Error Messages: {err_data['errorMessages']}"
                else:
                    detail = f"JIRA Response: {e.response.text}"
            except Exception:
                detail = f"JIRA Response: {e.response.text}"
        raise HTTPException(status_code=400, detail=f"Error al crear ticket en JIRA: {detail}")


def _parse_adf_to_text(adf) -> str:
    if not adf:
        return ""
    if isinstance(adf, str):
        return adf
    if not isinstance(adf, dict):
        return str(adf)
    texts = []
    def _walk(node):
        if isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "text":
                texts.append(node.get("text", ""))
            elif ntype in ("paragraph", "heading"):
                for child in node.get("content", []):
                    _walk(child)
                texts.append("\n")
            elif ntype == "hardBreak":
                texts.append("\n")
            else:
                for child in node.get("content", []):
                    _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
    _walk(adf)
    return "".join(texts).strip()


@router.get("/tickets/visits")
def get_visits(db: Session = Depends(get_db)):
    import re
    from sqlalchemy import select
    from app.models import JiraIssue
    
    issues = db.scalars(select(JiraIssue)).all()
    visits = []
    
    for issue in issues:
        fields = (issue.raw_payload or {}).get("fields") or {}
        # Tipo de atención
        tipo_atencion_field = fields.get(settings.jira_tipo_atencion_field_id)
        is_visita = False
        if isinstance(tipo_atencion_field, dict):
            val = tipo_atencion_field.get("value")
            opt_id = tipo_atencion_field.get("id")
            if val == "Visita Programada" or opt_id == "10406":
                is_visita = True
        elif isinstance(tipo_atencion_field, str):
            if tipo_atencion_field == "Visita Programada" or tipo_atencion_field == "10406":
                is_visita = True
                
        if not is_visita and issue.summary:
            if "visita" in issue.summary.lower():
                is_visita = True
            
        if is_visita:
            # Extract client name
            client_field = fields.get(settings.jira_client_field_id)
            client_name = client_field if isinstance(client_field, str) else "Sin Empresa"
            
            # Extract description text
            desc_field = fields.get("description")
            description = _parse_adf_to_text(desc_field)
            
            # Extract comments text
            comments_text = ""
            comment_dict = fields.get("comment") or {}
            if isinstance(comment_dict, dict):
                for c in comment_dict.get("comments", []):
                    comments_text += "\n" + _parse_adf_to_text(c.get("body"))
            combined_text = (description + "\n" + comments_text).strip()

            start_str = None
            end_str = None
            exact_parsed = False
            
            # Try to parse exact start/end datetimes from description or comments
            start_match = re.search(r"Inicio:\s*(\d{2}[-/]\d{2}[-/]\d{4}\s+\d{2}:\d{2})", combined_text, re.IGNORECASE)
            end_match = re.search(r"(?:T\u00e9rmino|Termino|Fin):\s*(\d{2}[-/]\d{2}[-/]\d{4}\s+\d{2}:\d{2})", combined_text, re.IGNORECASE)
            
            if start_match:
                try:
                    val = start_match.group(1).replace("-", "/").strip()
                    dt_start = datetime.strptime(val, "%d/%m/%Y %H:%M")
                    start_str = dt_start.isoformat()
                    exact_parsed = True
                except Exception:
                    pass
            if end_match:
                try:
                    val = end_match.group(1).replace("-", "/").strip()
                    dt_end = datetime.strptime(val, "%d/%m/%Y %H:%M")
                    end_str = dt_end.isoformat()
                except Exception:
                    pass
                    
            if not exact_parsed:
                start_date_field = fields.get(settings.jira_fecha_inicio_field_id)
                duedate_field = fields.get("duedate")
                
                target_date_str = None
                if start_date_field:
                    target_date_str = str(start_date_field).strip()[:10]
                elif duedate_field:
                    target_date_str = str(duedate_field).strip()[:10]
                elif issue.summary:
                    summary_date_match = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", issue.summary)
                    if summary_date_match:
                        day, month, year = summary_date_match.groups()
                        target_date_str = f"{year}-{month}-{day}"
                elif issue.created_at_jira:
                    target_date_str = issue.created_at_jira.strftime("%Y-%m-%d")
                    
                if target_date_str:
                    start_str = f"{target_date_str}T09:00:00"
                    end_str = f"{target_date_str}T10:00:00"
            
            # Agent
            agent_name = issue.assignee_agent.name if issue.assignee_agent else "Sin asignar"
            agent_account_id = issue.assignee_agent.jira_account_id if issue.assignee_agent else None
            
            # Service Level (SLA)
            service_level_field = fields.get(settings.jira_service_level_field_id)
            service_level = ""
            if isinstance(service_level_field, dict):
                service_level = service_level_field.get("value", "")
            elif isinstance(service_level_field, str):
                service_level = service_level_field
                
            # Ticket Category
            cat_field = fields.get(settings.jira_categoria_ticket_field_id)
            ticket_category = ""
            if isinstance(cat_field, list) and len(cat_field) > 0:
                if isinstance(cat_field[0], dict):
                    ticket_category = cat_field[0].get("value", "")
                else:
                    ticket_category = str(cat_field[0])
            elif isinstance(cat_field, dict):
                ticket_category = cat_field.get("value", "")
            elif isinstance(cat_field, str):
                ticket_category = cat_field
                
            visits.append({
                "id": issue.jira_key,
                "title": f"Visita {client_name} - {agent_name}",
                "start": start_str,
                "end": end_str,
                "extendedProps": {
                    "jira_key": issue.jira_key,
                    "summary": issue.summary,
                    "client": client_name,
                    "agent_name": agent_name,
                    "agent_account_id": agent_account_id,
                    "service_level": service_level,
                    "ticket_category": ticket_category,
                    "description": description,
                    "status": issue.status
                }
            })
            
    return visits


@router.put("/tickets/visits/{key}")
def update_visit_ticket(key: str, payload: VisitTicketUpdate, db: Session = Depends(get_db)):
    from app.services.jira import JiraClient
    from app.services.sync import sync_single_issue_by_key
    from app.models import JiraIssue, Agent
    from sqlalchemy import select
    from zoneinfo import ZoneInfo
    
    issue = db.scalar(select(JiraIssue).where(JiraIssue.jira_key == key))
    if not issue:
        raise HTTPException(status_code=404, detail="Ticket no encontrado localmente.")
        
    fields = (issue.raw_payload or {}).get("fields") or {}
    client_field = fields.get(settings.jira_client_field_id)
    company_name = client_field if isinstance(client_field, str) else "Sin Empresa"
    
    # 1. Determine agent
    agent_name = "No asignado"
    assignee_id = None
    if payload.assignee_account_id:
        agent = db.scalar(select(Agent).where(Agent.jira_account_id == payload.assignee_account_id))
        agent_name = agent.name if agent else "No asignado"
        assignee_id = payload.assignee_account_id
    elif issue.assignee_agent:
        agent_name = issue.assignee_agent.name
        assignee_id = issue.assignee_agent.jira_account_id
        
    # 2. Convert datetimes to local timezone
    app_tz = ZoneInfo(settings.app_timezone)
    start_local = payload.start_date.astimezone(app_tz)
    end_local = payload.end_date.astimezone(app_tz)
    
    start_str = start_local.strftime("%d/%m/%Y %H:%M")
    end_str = end_local.strftime("%d/%m/%Y %H:%M")
    
    # 3. Rebuild description
    # Get current description text
    current_desc = ""
    desc_field = fields.get("description")
    if isinstance(desc_field, dict):
        try:
            texts = []
            for content_item in desc_field.get("content", []):
                for text_item in content_item.get("content", []):
                    if text_item.get("type") == "text":
                        texts.append(text_item.get("text", ""))
            current_desc = "\n".join(texts)
        except Exception:
            current_desc = str(desc_field)
    elif isinstance(desc_field, str):
        current_desc = desc_field
        
    # Extract only user text lines
    lines = current_desc.split("\n")
    user_lines = []
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue
        if clean_line.startswith("Profesional Asignado:") or clean_line.startswith("Cliente:") or clean_line.startswith("Inicio:") or clean_line.startswith("Término:"):
            continue
        user_lines.append(line)
    user_desc_text = "\n".join(user_lines).strip()
    
    final_desc_text = payload.description.strip() if (payload.description is not None) else user_desc_text
    
    # Rebuild ADF
    adf_content = [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Profesional Asignado: "},
                {"type": "text", "text": agent_name, "marks": [{"type": "strong"}]}
            ]
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Cliente: "},
                {"type": "text", "text": company_name.upper(), "marks": [{"type": "strong"}]}
            ]
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Inicio: "},
                {"type": "text", "text": start_str}
            ]
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Término: "},
                {"type": "text", "text": end_str}
            ]
        }
    ]
    
    if final_desc_text:
        adf_content.append({"type": "paragraph", "content": []})
        adf_content.append({
            "type": "paragraph",
            "content": [
                {"type": "text", "text": final_desc_text}
            ]
        })
        
    adf_description = {
        "type": "doc",
        "version": 1,
        "content": adf_content
    }
    
    # 4. Compile JIRA fields
    jira_fields = {
        "description": adf_description,
        settings.jira_fecha_inicio_field_id: start_local.strftime("%Y-%m-%d"),
        "duedate": end_local.strftime("%Y-%m-%d"),
    }
    if assignee_id is not None:
        jira_fields["assignee"] = {"accountId": assignee_id}
    else:
        jira_fields["assignee"] = None
        
    if payload.service_level:
        jira_fields[settings.jira_service_level_field_id] = {"value": "L2" if payload.service_level == "L1/L2" else payload.service_level}
    if payload.ticket_category:
        jira_fields[settings.jira_categoria_ticket_field_id] = [{"value": payload.ticket_category}]
        
    try:
        jira = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
        jira.update_issue(key, jira_fields)
        sync_single_issue_by_key(db, key)
        return {"status": "ok", "key": key}
    except Exception as e:
        detail = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                err_data = e.response.json()
                if "errors" in err_data:
                    detail = f"JIRA Errors: {err_data['errors']}"
                elif "errorMessages" in err_data:
                    detail = f"JIRA Error Messages: {err_data['errorMessages']}"
                else:
                    detail = f"JIRA Response: {e.response.text}"
            except Exception:
                detail = f"JIRA Response: {e.response.text}"
        raise HTTPException(status_code=400, detail=f"Error al actualizar ticket en JIRA: {detail}")

