"""
MCP Server for Jira Reports & Operations.
Exposes tools for hours consumption analysis, visits reporting, ticket inquiries, client/agent listings, and Jira synchronization.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from sqlalchemy import select
from mcp.server.fastmcp import FastMCP

from app.db import SessionLocal
from app.models import Agent, Client, JiraIssue
from app.services.reports import (
    build_hours_consumption_report,
    build_visits_report,
    build_tickets_report,
    get_distinct_issue_statuses,
)
from app.services.sync import sync_from_jira

# Initialize FastMCP Server
mcp = FastMCP("Jira Reports Service")


@mcp.tool()
def get_hours_consumption(
    start_date: str,
    end_date: str,
    client_name: Optional[str] = None,
    agent_id: Optional[int] = None,
    service_level: Optional[str] = None,
    statuses: Optional[list[str]] = None,
) -> dict:
    """
    Obtiene el reporte y métricas de consumo de horas (soporte y proyectos) en un rango de fechas.
    
    :param start_date: Fecha inicial en formato YYYY-MM-DD (ej: '2026-05-01')
    :param end_date: Fecha final en formato YYYY-MM-DD (ej: '2026-05-31')
    :param client_name: Nombre o filtro de cliente/empresa (opcional)
    :param agent_id: ID del técnico o agente (opcional)
    :param service_level: Nivel de servicio (ej: 'L1/L2', 'L3', 'TERRENO', 'PROYECTO')
    :param statuses: Lista de estados de ticket a filtrar (ej: ['Cerrado', 'En Progreso'])
    """
    d_start = date.fromisoformat(start_date)
    d_end = date.fromisoformat(end_date)
    with SessionLocal() as db:
        return build_hours_consumption_report(
            db,
            start_date=d_start,
            end_date=d_end,
            client_text=client_name,
            agent_id=agent_id,
            service_level=service_level,
            statuses=statuses,
        )


@mcp.tool()
def get_visits_report(
    start_date: str,
    end_date: str,
    client_name: Optional[str] = None,
    agent_id: Optional[int] = None,
    visit_type: Optional[str] = None,
) -> dict:
    """
    Obtiene el reporte de visitas presenciales clasificadas en Visitas Programadas y Visitas No Programadas.
    
    :param start_date: Fecha inicial en formato YYYY-MM-DD (ej: '2026-05-01')
    :param end_date: Fecha final en formato YYYY-MM-DD (ej: '2026-05-31')
    :param client_name: Nombre del cliente o empresa a filtrar (opcional)
    :param agent_id: ID del técnico asignado (opcional)
    :param visit_type: Tipo de visita a filtrar: 'Visita Programada' o 'Visita No Programada' (opcional)
    """
    d_start = date.fromisoformat(start_date)
    d_end = date.fromisoformat(end_date)
    with SessionLocal() as db:
        return build_visits_report(
            db,
            start_date=d_start,
            end_date=d_end,
            client_text=client_name,
            agent_id=agent_id,
            visit_type=visit_type,
        )


@mcp.tool()
def get_client_tickets(
    start_date: str,
    end_date: str,
    client_name: Optional[str] = None,
    status: Optional[str] = None,
    service_level: Optional[str] = None,
) -> dict:
    """
    Consulta los tickets gestionados en un rango de fechas con filtros por cliente, estado y nivel.
    
    :param start_date: Fecha de inicio en formato YYYY-MM-DD
    :param end_date: Fecha de término en formato YYYY-MM-DD
    :param client_name: Nombre del cliente (opcional)
    :param status: Estado del ticket (ej: 'Pendiente', 'Cerrado', 'En Espera')
    :param service_level: Nivel de servicio (opcional)
    """
    d_start = date.fromisoformat(start_date)
    d_end = date.fromisoformat(end_date)
    with SessionLocal() as db:
        return build_tickets_report(
            db,
            start_date=d_start,
            end_date=d_end,
            client_text=client_name,
            status=status,
            service_level=service_level,
        )


@mcp.tool()
def list_clients() -> list[dict]:
    """
    Lista todos los clientes registrados y activos en el sistema.
    """
    with SessionLocal() as db:
        clients = db.scalars(select(Client).where(Client.active == True).order_by(Client.name)).all()
        return [{"id": c.id, "name": c.name, "jira_account_id": c.jira_account_id} for c in clients]


@mcp.tool()
def list_agents() -> list[dict]:
    """
    Lista todos los técnicos y agentes registrados en el sistema.
    """
    with SessionLocal() as db:
        agents = db.scalars(select(Agent).where(Agent.active == True).order_by(Agent.name)).all()
        return [{"id": a.id, "name": a.name, "jira_account_id": a.jira_account_id} for a in agents]


@mcp.tool()
def list_statuses() -> list[str]:
    """
    Retorna la lista de todos los estados de ticket disponibles en Jira.
    """
    with SessionLocal() as db:
        return get_distinct_issue_statuses(db)


@mcp.tool()
def trigger_jira_sync(force_all: bool = False) -> dict:
    """
    Dispara la sincronización de tickets y registros de trabajo desde Jira Cloud hacia la base de datos local.
    
    :param force_all: Si es True, realiza una sincronización completa sin límite de fecha incremental.
    """
    with SessionLocal() as db:
        result = sync_from_jira(db, full=force_all)
        return {"status": "ok", "result": result}


if __name__ == "__main__":
    import sys
    if "--sse" in sys.argv or "-s" in sys.argv:
        mcp.run(transport="sse")
    else:
        mcp.run()
