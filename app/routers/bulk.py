"""
Router de API para Operaciones y Edición Masiva de Tickets en Jira.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.models.entities import User
from app.routers.auth import get_current_user_optional
from app.services.bulk import (
    apply_bulk_operation_single,
    build_jql_from_filters,
    get_bulk_metadata,
    search_issues_for_bulk,
)
from app.services.jira import JiraClient

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/bulk", tags=["bulk"])


def get_jira_client() -> JiraClient:
    if not settings.jira_base_url or not settings.jira_email or not settings.jira_api_token:
        raise HTTPException(
            status_code=400,
            detail="La conexión con la API de Jira no está configurada en los parámetros de la aplicación.",
        )
    return JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)


class BulkFilterRequest(BaseModel):
    project: str | None = None
    status: str | None = None
    organization: str | None = None
    label: str | None = None
    search_text: str | None = None
    custom_jql: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


class BulkExecuteRequest(BaseModel):
    issue_keys: list[str]
    operation: str
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True


@router.get("/metadata")
def get_metadata(
    current_user: User | None = Depends(get_current_user_optional),
    jira: JiraClient = Depends(get_jira_client),
):
    """Retorna proyectos, estados y organizaciones reales desde Jira para popular los filtros."""
    try:
        return get_bulk_metadata(jira)
    except Exception as e:
        logger.error(f"Error al obtener metadatos de Jira: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preview")
def preview_issues(
    payload: BulkFilterRequest,
    current_user: User | None = Depends(get_current_user_optional),
    jira: JiraClient = Depends(get_jira_client),
):
    """Busca y previsualiza tickets que coinciden con los filtros o JQL."""
    try:
        jql = build_jql_from_filters(
            project=payload.project,
            status=payload.status,
            organization=payload.organization,
            label=payload.label,
            search_text=payload.search_text,
            custom_jql=payload.custom_jql,
        )
        issues = search_issues_for_bulk(jira, jql=jql, limit=payload.limit)
        return {
            "jql": jql,
            "total_found": len(issues),
            "issues": issues,
        }
    except Exception as e:
        logger.error(f"Error al previsualizar tickets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute")
def execute_bulk(
    payload: BulkExecuteRequest,
    current_user: User | None = Depends(get_current_user_optional),
    jira: JiraClient = Depends(get_jira_client),
):
    """Ejecuta la modificación masiva (o simulación Dry Run) sobre la lista de tickets."""
    if not payload.issue_keys:
        raise HTTPException(status_code=400, detail="Debe seleccionar al menos un ticket.")

    results = []
    success_count = 0
    fail_count = 0

    for key in payload.issue_keys:
        res = apply_bulk_operation_single(
            jira=jira,
            issue_key=key,
            operation=payload.operation,
            params=payload.params,
            dry_run=payload.dry_run,
        )
        results.append(res)
        if res.get("success"):
            success_count += 1
        else:
            fail_count += 1

    return {
        "dry_run": payload.dry_run,
        "total": len(payload.issue_keys),
        "success_count": success_count,
        "fail_count": fail_count,
        "results": results,
    }
