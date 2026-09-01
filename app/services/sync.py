from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Agent, Client, JiraIssue, JiraWorklog, Organization, SyncState
from app.services.jira import JiraClient, jira_user_to_dict, parse_jira_datetime


settings = get_settings()


def _normalize_comment(worklog: dict) -> str | None:
    comment = worklog.get("comment")
    if comment is None:
        return None
    if isinstance(comment, dict):
        return str(comment)
    return str(comment)


def _normalize_organizations(raw_value) -> list[dict[str, str | None]]:
    if not raw_value:
        return []
    items = raw_value if isinstance(raw_value, list) else [raw_value]
    normalized: list[dict[str, str | None]] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            org_id = item.get("id") or item.get("organizationId") or item.get("value")
            name = item.get("name") or item.get("label") or item.get("displayName")
            normalized.append({"id": str(org_id) if org_id is not None else None, "name": str(name) if name else None})
        else:
            normalized.append({"id": str(item), "name": None})
    return normalized


def _extract_text_field(fields: dict, field_id: str) -> str | None:
    value = fields.get(field_id)
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("value", "text", "name", "label"):
            if value.get(key):
                return str(value.get(key)).strip() or None
        return str(value).strip() or None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if item is not None and str(item).strip()]
        return ", ".join(parts) if parts else None
    return str(value).strip() or None


def _upsert_organization(session: Session, org_id: str | None, name: str) -> Organization:
    obj = None
    if org_id:
        obj = session.scalar(select(Organization).where(Organization.jira_organization_id == org_id))
    if obj is None:
        obj = session.scalar(select(Organization).where(Organization.name == name))
    if obj is None:
        obj = Organization(jira_organization_id=org_id, name=name, active=True)
        session.add(obj)
    else:
        obj.jira_organization_id = org_id or obj.jira_organization_id
        obj.name = name
        obj.active = True
    return obj


def _sync_organizations(session: Session, jira: JiraClient) -> dict[str, Organization]:
    organizations: dict[str, Organization] = {}
    start = 0
    limit = 50
    while True:
        payload = jira.list_organizations(start=start, limit=limit)
        values = payload.get("values", [])
        for item in values:
            org = _upsert_organization(session, str(item.get("id")) if item.get("id") is not None else None, item.get("name") or "Sin nombre")
            if org.jira_organization_id:
                organizations[org.jira_organization_id] = org
        session.flush()
        if payload.get("isLastPage", True):
            break
        start += limit
    return organizations


def _upsert_person(session: Session, model, jira_user):
    if jira_user is None:
        return None
    account_id = jira_user.account_id
    obj = None
    if account_id:
        obj = session.scalar(select(model).where(model.jira_account_id == account_id))
    if obj is None:
        obj = session.scalar(select(model).where(model.name == jira_user.display_name))
    if obj is None:
        obj = model(jira_account_id=account_id, name=jira_user.display_name, email=jira_user.email)
        session.add(obj)
        session.flush()
    else:
        obj.jira_account_id = account_id or obj.jira_account_id
        obj.name = jira_user.display_name
        obj.email = jira_user.email or obj.email
        obj.active = True
    return obj


def _get_state(session: Session, name: str) -> SyncState:
    state = session.scalar(select(SyncState).where(SyncState.name == name))
    if state is None:
        state = SyncState(name=name, value=None)
        session.add(state)
        session.flush()
    return state


def _split_order_by(jql: str) -> tuple[str, str | None]:
    match = re.search(r"\border\s+by\b", jql, flags=re.IGNORECASE)
    if not match:
        return jql.strip(), None
    return jql[: match.start()].strip(), jql[match.start() :].strip()


def _compose_sync_jql(from_date: date | None, to_date: date | None) -> str:
    base_jql, order_by = _split_order_by(settings.jira_jql)
    clauses = [f"({base_jql})"] if base_jql else []
    if from_date is not None:
        clauses.append(f'updated >= "{from_date.isoformat()}"')
    # Omitimos el to_date en la JQL para asegurarnos de traer los tickets que se hayan actualizado hoy
    # aunque el usuario esté consultando un rango de fechas del pasado.
    jql = " AND ".join(clauses) if clauses else base_jql
    if order_by:
        return f"{jql} {order_by}"
    return f"{jql} ORDER BY updated DESC" if jql else "ORDER BY updated DESC"


def _sync_single_issue(session: Session, jira: JiraClient, issue_payload: dict, organizations_by_id: dict[str, Organization]) -> tuple[int, int]:
    fields = issue_payload.get("fields", {})
    jira_id = issue_payload.get("id")
    jira_key = issue_payload.get("key")
    updated_at = parse_jira_datetime(fields.get("updated"))
    created_at = parse_jira_datetime(fields.get("created"))
    resolved_at = parse_jira_datetime(fields.get("resolutiondate"))
    issue_type = (fields.get("issuetype") or {}).get("name") or "Desconocido"
    status = (fields.get("status") or {}).get("name") or "Desconocido"
    priority = (fields.get("priority") or {}).get("name")
    project_key = (fields.get("project") or {}).get("key") or "UNK"
    summary = fields.get("summary") or jira_key
    reporter = jira_user_to_dict(fields.get("reporter"))
    assignee = jira_user_to_dict(fields.get("assignee"))
    org_values = _normalize_organizations(fields.get(settings.jira_organization_field_id))
    client_text = _extract_text_field(fields, settings.jira_client_field_id)
    reporter_obj = _upsert_person(session, Client, reporter)
    assignee_obj = _upsert_person(session, Agent, assignee)
    is_incident = "incident" in issue_type.lower()

    issue = session.scalar(select(JiraIssue).where(JiraIssue.jira_id == jira_id))
    needs_worklog_sync = issue is None or (issue.updated_at_jira is None) or (updated_at and issue.updated_at_jira and updated_at != issue.updated_at_jira)

    issues_upserted = 0
    worklogs_upserted = 0

    if issue is None:
        issue = JiraIssue(
            jira_id=jira_id,
            jira_key=jira_key,
            summary=summary,
            project_key=project_key,
            issue_type=issue_type,
            status=status,
            priority=priority,
            is_incident=is_incident,
            created_at_jira=created_at,
            updated_at_jira=updated_at,
            resolved_at_jira=resolved_at,
            raw_payload=issue_payload,
        )
        session.add(issue)
        issues_upserted = 1
    else:
        issue.jira_key = jira_key
        issue.summary = summary
        issue.project_key = project_key
        issue.issue_type = issue_type
        issue.status = status
        issue.priority = priority
        issue.is_incident = is_incident
        issue.created_at_jira = created_at
        issue.updated_at_jira = updated_at
        issue.resolved_at_jira = resolved_at
        issue.raw_payload = issue_payload
        issues_upserted = 1

    issue.reporter_client = reporter_obj
    issue.assignee_agent = assignee_obj
    if issue.raw_payload is None:
        issue.raw_payload = issue_payload
    issue.raw_payload = issue_payload
    if client_text:
        issue.raw_payload.setdefault("fields", {})
        issue.raw_payload["fields"][settings.jira_client_field_id] = client_text
    issue.organizations = []
    for org_value in org_values:
        org_id = org_value.get("id")
        org_name = org_value.get("name") or "Sin nombre"
        org = organizations_by_id.get(org_id) if org_id else None
        if org is None:
            org = _upsert_organization(session, org_id, org_name)
            if org.jira_organization_id:
                organizations_by_id[org.jira_organization_id] = org
        issue.organizations.append(org)
    session.flush()

    if needs_worklog_sync:
        worklog_payload = jira.get_issue_worklogs(jira_key)
        seen_worklog_ids = set()
        for worklog in worklog_payload.get("worklogs", []):
            worklog_id = str(worklog.get("id"))
            seen_worklog_ids.add(worklog_id)
            started_at = parse_jira_datetime(worklog.get("started"))
            updated_worklog_at = parse_jira_datetime(worklog.get("updated"))
            author = jira_user_to_dict(worklog.get("author"))
            author_obj = _upsert_person(session, Agent, author)
            existing = session.scalar(select(JiraWorklog).where(JiraWorklog.jira_worklog_id == worklog_id))
            if existing is None:
                existing = JiraWorklog(
                    jira_worklog_id=worklog_id,
                    issue=issue,
                    author_agent=author_obj,
                    started_at=started_at,
                    updated_at_jira=updated_worklog_at,
                    time_spent_seconds=int(worklog.get("timeSpentSeconds") or 0),
                    comment=_normalize_comment(worklog),
                    raw_payload=worklog,
                )
                session.add(existing)
                worklogs_upserted += 1
            else:
                existing.issue = issue
                existing.author_agent = author_obj
                existing.started_at = started_at
                existing.updated_at_jira = updated_worklog_at
                existing.time_spent_seconds = int(worklog.get("timeSpentSeconds") or 0)
                existing.comment = _normalize_comment(worklog)
                existing.raw_payload = worklog
                worklogs_upserted += 1
        
        # Borrar worklogs que fueron eliminados en Jira
        db_worklogs = session.scalars(select(JiraWorklog).where(JiraWorklog.issue_id == issue.id)).all()
        for db_w in db_worklogs:
            if db_w.jira_worklog_id not in seen_worklog_ids:
                session.delete(db_w)

    return issues_upserted, worklogs_upserted


def sync_from_jira(session: Session, from_date: date | None = None, to_date: date | None = None) -> dict:
    if not (settings.jira_base_url and settings.jira_email and settings.jira_api_token):
        raise RuntimeError("Faltan credenciales de Jira en variables de entorno.")

    jira = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
    sync_jql = _compose_sync_jql(from_date, to_date)
    organizations_by_id = _sync_organizations(session, jira)
    issues_seen = 0
    issues_upserted = 0
    worklogs_upserted = 0
    next_page_token: str | None = None
    max_results = settings.sync_page_size
    max_issues = settings.sync_max_issues
    
    subtask_keys_to_sync = set()
    synced_issue_keys = set()

    while issues_seen < max_issues:
        payload = jira.search_issues(
            sync_jql,
            max_results=max_results,
            next_page_token=next_page_token,
            extra_fields=[
                settings.jira_organization_field_id,
                settings.jira_client_field_id,
                settings.jira_service_level_field_id,
            ],
        )
        issues = payload.get("issues", [])
        if not issues:
            break

        for issue_payload in issues:
            issues_seen += 1
            key = issue_payload.get("key")
            if key:
                synced_issue_keys.add(key)
            
            fields = issue_payload.get("fields", {})
            subtasks = fields.get("subtasks", [])
            for sub in subtasks:
                sub_key = sub.get("key")
                if sub_key:
                    subtask_keys_to_sync.add(sub_key)

            ups_iss, ups_wl = _sync_single_issue(session, jira, issue_payload, organizations_by_id)
            issues_upserted += ups_iss
            worklogs_upserted += ups_wl

        next_page_token = payload.get("nextPageToken")
        if payload.get("isLast", True) or not next_page_token:
            break

    missing_subtask_keys = subtask_keys_to_sync - synced_issue_keys
    if missing_subtask_keys:
        keys_list = list(missing_subtask_keys)
        batch_size = 50
        for i in range(0, len(keys_list), batch_size):
            batch_keys = keys_list[i : i + batch_size]
            sub_jql = f"key in ({','.join(batch_keys)})"
            sub_payload = jira.search_issues(
                sub_jql,
                max_results=50,
                extra_fields=[
                    settings.jira_organization_field_id,
                    settings.jira_client_field_id,
                    settings.jira_service_level_field_id,
                ],
            )
            for sub_issue_payload in sub_payload.get("issues", []):
                ups_iss, ups_wl = _sync_single_issue(session, jira, sub_issue_payload, organizations_by_id)
                issues_upserted += ups_iss
                worklogs_upserted += ups_wl

    state = _get_state(session, "jira_last_sync")
    state.value = datetime.now(timezone.utc).isoformat()
    session.commit()
    return {"issues_seen": issues_seen, "issues_upserted": issues_upserted, "worklogs_upserted": worklogs_upserted}


def sync_single_issue_by_key(session: Session, key: str) -> None:
    if not (settings.jira_base_url and settings.jira_email and settings.jira_api_token):
        return

    jira = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
    url = f"{jira.base_url}/rest/api/3/issue/{key}"
    res = jira.session.get(url, params={
        "fields": ",".join([
            "summary", "issuetype", "status", "priority", "project", "assignee", "reporter",
            "created", "updated", "resolutiondate", "subtasks", "parent",
            settings.jira_organization_field_id,
            settings.jira_client_field_id,
            settings.jira_service_level_field_id
        ])
    }, timeout=60)
    res.raise_for_status()
    issue_payload = res.json()
    organizations_by_id = _sync_organizations(session, jira)
    _sync_single_issue(session, jira, issue_payload, organizations_by_id)
    session.commit()
