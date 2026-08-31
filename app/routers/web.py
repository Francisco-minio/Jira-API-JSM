from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_db
from app.models.entities import User
from app.routers.auth import get_current_user_optional

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["web"])
settings = get_settings()


def _require_user(current_user: Optional[User]):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    return None


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    end = date.today()
    start = end - timedelta(days=30)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "default_from": start.isoformat(),
            "default_to": end.isoformat(),
            "jira_base_url": settings.jira_base_url,
            "current_user": current_user,
        },
    )


@router.get("/tickets", response_class=HTMLResponse)
def tickets(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    end = date.today()
    start = end - timedelta(days=30)
    return templates.TemplateResponse(
        request=request,
        name="tickets.html",
        context={
            "default_from": start.isoformat(),
            "default_to": end.isoformat(),
            "jira_base_url": settings.jira_base_url,
            "current_user": current_user,
        },
    )


@router.get("/agents", response_class=HTMLResponse)
def agents(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    end = date.today()
    start = end - timedelta(days=30)
    return templates.TemplateResponse(
        request=request,
        name="agents.html",
        context={
            "default_from": start.isoformat(),
            "default_to": end.isoformat(),
            "jira_base_url": settings.jira_base_url,
            "current_user": current_user,
        },
    )


@router.get("/configuration", response_class=HTMLResponse)
def configuration(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    return templates.TemplateResponse(
        request=request,
        name="configuration.html",
        context={
            "settings": settings,
            "current_user": current_user,
        },
    )


@router.get("/clients-visits", response_class=HTMLResponse)
def clients_visits(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    return templates.TemplateResponse(
        request=request,
        name="clients_visits.html",
        context={
            "jira_base_url": settings.jira_base_url,
            "current_user": current_user,
        },
    )


@router.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context={
            "jira_base_url": settings.jira_base_url,
            "current_user": current_user,
        },
    )


@router.get("/hours-consumption", response_class=HTMLResponse)
def hours_consumption(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    end = date.today()
    start = end - timedelta(days=30)
    return templates.TemplateResponse(
        request=request,
        name="hours_consumption.html",
        context={
            "default_from": start.isoformat(),
            "default_to": end.isoformat(),
            "jira_base_url": settings.jira_base_url,
            "current_user": current_user,
        },
    )


@router.get("/visits-report", response_class=HTMLResponse)
def visits_report(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    redir = _require_user(current_user)
    if redir:
        return redir

    end = date.today()
    start = end - timedelta(days=30)
    return templates.TemplateResponse(
        request=request,
        name="visits_report.html",
        context={
            "default_from": start.isoformat(),
            "default_to": end.isoformat(),
            "jira_base_url": settings.jira_base_url,
            "current_user": current_user,
        },
    )
