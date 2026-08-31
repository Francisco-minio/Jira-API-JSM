from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import re
import unicodedata
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import Agent, Client, CompanyInformer, JiraIssue, JiraWorklog, Organization
from app.services.calendar import business_days_between, chile_holiday_names, expected_capacity_hours, to_tz_aware


settings = get_settings()
app_tz = ZoneInfo(settings.app_timezone)


def _build_subtask_maps(session: Session) -> tuple[dict[int, list[int]], dict[int, int], dict[int, str]]:
    issues = session.execute(
        select(JiraIssue.id, JiraIssue.jira_key, JiraIssue.raw_payload)
    ).all()
    
    key_to_id = {row.jira_key: row.id for row in issues}
    id_to_key = {row.id: row.jira_key for row in issues}
    
    parent_to_children = defaultdict(list)
    child_to_parent = {}
    
    for row in issues:
        raw_payload = row.raw_payload or {}
        fields = raw_payload.get("fields") or {}
        
        # Vía 1: Campo parent en la subtarea
        parent_key = fields.get("parent", {}).get("key")
        if parent_key and parent_key in key_to_id:
            parent_id = key_to_id[parent_key]
            parent_to_children[parent_id].append(row.id)
            child_to_parent[row.id] = parent_id
            continue
            
        # Vía 2: Campo subtasks en el padre
        subtasks = fields.get("subtasks", [])
        for sub in subtasks:
            sub_key = sub.get("key")
            if sub_key and sub_key in key_to_id:
                sub_id = key_to_id[sub_key]
                parent_to_children[row.id].append(sub_id)
                child_to_parent[sub_id] = row.id
                
    return dict(parent_to_children), child_to_parent, id_to_key


def _range_start(value: date) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=app_tz)


def _range_end(value: date) -> datetime:
    return datetime.combine(value, datetime.max.time(), tzinfo=app_tz)


def _date_label(dt: datetime | None) -> str:
    if dt is None:
        return "Sin fecha"
    local = to_tz_aware(dt, settings.app_timezone)
    return local.strftime("%Y-%m-%d")


def _month_label(dt: datetime | None) -> str:
    if dt is None:
        return "Sin fecha"
    local = to_tz_aware(dt, settings.app_timezone)
    return local.strftime("%Y-%m")


def _extract_issue_field_text(issue: JiraIssue, field_id: str) -> str | None:
    payload = issue.raw_payload or {}
    fields = payload.get("fields") or {}
    value = fields.get(field_id)
    
    def _parse(val) -> str | None:
        if val is None:
            return None
        if isinstance(val, str):
            text = val.strip()
            return text or None
        if isinstance(val, dict):
            for key in ("value", "text", "name", "label"):
                if val.get(key):
                    return str(val.get(key)).strip() or None
            return str(val).strip() or None
        if isinstance(val, list):
            parts = []
            for item in val:
                parsed = _parse(item)
                if parsed:
                    parts.append(parsed)
            return ", ".join(parts) if parts else None
        return str(val).strip() or None

    return _parse(value)


def _extract_client_text(issue: JiraIssue) -> str | None:
    return _extract_issue_field_text(issue, settings.jira_client_field_id)


def _extract_service_level_text(issue: JiraIssue) -> str | None:
    return _extract_issue_field_text(issue, settings.jira_service_level_field_id)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text or None


def _normalize_client_filter(client_text: str | None) -> str | None:
    return _normalize_text(client_text)


def _issue_client_label(issue: JiraIssue) -> str:
    return _extract_client_text(issue) or "Sin cliente"


def _issue_matches_client(issue: JiraIssue, normalized_client: str | None) -> bool:
    if normalized_client is None:
        return True
    return _normalize_text(_issue_client_label(issue)) == normalized_client


def _issue_service_level_label(issue: JiraIssue) -> str:
    val = _extract_service_level_text(issue)
    if val:
        norm = val.strip().upper()
        if norm in ("L1", "L2"):
            return "L1/L2"
        return val
    return "Sin nivel"


def _service_level_sort_key(value: str) -> tuple[int, str]:
    normalized = _normalize_text(value) or "sin-nivel"
    order = {
        "l1/l2": 1,
        "l1": 1,
        "l2": 2,
        "l3": 3,
        "sin nivel": 90,
        "sin-nivel": 90,
    }.get(normalized, 50)
    return (order, normalized)


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _format_display_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _holiday_names_for_week(week_start: date, start_date: date, end_date: date) -> list[str]:
    holiday_map = chile_holiday_names(list(range(start_date.year, end_date.year + 1)))
    names: list[str] = []
    for offset in range(5):
        candidate = week_start + timedelta(days=offset)
        if candidate < start_date or candidate > end_date:
            continue
        holiday_name = holiday_map.get(candidate)
        if holiday_name:
            names.append(holiday_name)
    return names


def _issue_in_window(issue: JiraIssue, start_date: date, end_date: date, worklog_issue_ids: set[int]) -> bool:
    return (
        issue.created_at_jira is not None
        and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date)
    ) or issue.id in worklog_issue_ids



def get_issues_and_worklogs_in_range(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> tuple[list[JiraIssue], list[JiraWorklog]]:
    normalized_client = _normalize_client_filter(client_text)
    _, child_to_parent, _ = _build_subtask_maps(session)
    
    worklogs = session.scalars(
        select(JiraWorklog).options(selectinload(JiraWorklog.author_agent)).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()

    for w in worklogs:
        if w.issue_id in child_to_parent:
            w.issue_id = child_to_parent[w.issue_id]

    worklog_issue_ids = {w.issue_id for w in worklogs}

    issues = session.scalars(
        select(JiraIssue).options(
            selectinload(JiraIssue.organizations),
            selectinload(JiraIssue.assignee_agent)
        ).where(
            or_(
                and_(
                    JiraIssue.created_at_jira.is_not(None),
                    JiraIssue.created_at_jira >= _range_start(start_date),
                    JiraIssue.created_at_jira <= _range_end(end_date),
                ),
                JiraIssue.id.in_(worklog_issue_ids) if worklog_issue_ids else False,
            )
        )
    ).all()

    # Filter out subtasks from issues list
    issues = [issue for issue in issues if issue.id not in child_to_parent]

    if normalized_client is not None:
        issues = [issue for issue in issues if _issue_matches_client(issue, normalized_client)]
        matching_issue_ids = {issue.id for issue in issues}
        worklogs = [w for w in worklogs if w.issue_id in matching_issue_ids]

    return issues, worklogs


def build_ticket_client_options(session: Session, start_date: date, end_date: date) -> list[dict]:
    _, child_to_parent, _ = _build_subtask_maps(session)
    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issue_hours: dict[int, float] = defaultdict(float)
    worklog_issue_ids: set[int] = set()
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600
        worklog_issue_ids.add(eff_id)

    issues = session.scalars(
        select(JiraIssue).where(
            or_(
                and_(
                    JiraIssue.created_at_jira.is_not(None),
                    JiraIssue.created_at_jira >= _range_start(start_date),
                    JiraIssue.created_at_jira <= _range_end(end_date),
                ),
                JiraIssue.id.in_(worklog_issue_ids) if worklog_issue_ids else False,
            )
        )
    ).all()

    issues = [issue for issue in issues if issue.id not in child_to_parent]

    bucket: dict[str, dict[str, object]] = {}
    for issue in issues:
        raw_client_text = _extract_client_text(issue) or "Sin cliente"
        client_key = _normalize_text(raw_client_text) or "sin-cliente"
        if client_key not in bucket:
            bucket[client_key] = {
                "client_text": raw_client_text,
                "client_key": client_key,
                "tickets": 0,
                "hours_logged": 0.0,
                "incidents": 0,
                "labels": defaultdict(int),
            }
        data = bucket[client_key]
        labels = data["labels"]
        if isinstance(labels, defaultdict):
            labels[raw_client_text] += 1
        if issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date):
            data["tickets"] = int(data["tickets"]) + 1
        if issue.id in worklog_issue_ids:
            data["hours_logged"] = round(float(data["hours_logged"]) + issue_hours.get(issue.id, 0.0), 2)
        if issue.is_incident and _issue_in_window(issue, start_date, end_date, worklog_issue_ids):
            data["incidents"] = int(data["incidents"]) + 1

    result: list[dict] = []
    for data in bucket.values():
        labels = data.pop("labels", None)
        if isinstance(labels, defaultdict) and labels:
            data["client_text"] = max(labels.items(), key=lambda item: (item[1], item[0].casefold()))[0]
        result.append(data)
    return sorted(result, key=lambda item: str(item["client_text"]).lower())


def build_service_level_report(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> list[dict]:
    normalized_client = _normalize_client_filter(client_text)
    _, child_to_parent, _ = _build_subtask_maps(session)
    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issue_hours: dict[int, float] = defaultdict(float)
    issue_worklog_count: dict[int, int] = defaultdict(int)
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600
        issue_worklog_count[eff_id] += 1

    issues = session.scalars(
        select(JiraIssue).options(selectinload(JiraIssue.organizations)).where(
            or_(
                and_(
                    JiraIssue.created_at_jira.is_not(None),
                    JiraIssue.created_at_jira >= _range_start(start_date),
                    JiraIssue.created_at_jira <= _range_end(end_date),
                ),
                JiraIssue.id.in_(issue_hours.keys()) if issue_hours else False,
            )
        )
    ).all()
    
    issues = [issue for issue in issues if issue.id not in child_to_parent]
    
    if normalized_client is not None:
        issues = [issue for issue in issues if _issue_matches_client(issue, normalized_client)]

    bucket: dict[str, dict[str, object]] = {}
    for issue in issues:
        level_text = _issue_service_level_label(issue)
        level_key = _normalize_text(level_text) or "sin-nivel"
        if level_key not in bucket:
            bucket[level_key] = {
                "service_level": level_text,
                "tickets_registered": 0,
                "tickets_attended": 0,
                "hours_logged": 0.0,
                "incidents": 0,
            }
        data = bucket[level_key]
        if issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date):
            data["tickets_registered"] = int(data["tickets_registered"]) + 1
        if issue.id in issue_worklog_count and issue_worklog_count[issue.id] > 0:
            data["tickets_attended"] = int(data["tickets_attended"]) + 1
        if issue.id in issue_hours:
            data["hours_logged"] = round(float(data["hours_logged"]) + issue_hours.get(issue.id, 0.0), 2)
        if issue.is_incident and issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date):
            data["incidents"] = int(data["incidents"]) + 1

    result = list(bucket.values())
    return sorted(result, key=lambda item: _service_level_sort_key(str(item["service_level"])))


def build_overview(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> dict:
    normalized_client = _normalize_client_filter(client_text)
    issues, worklogs = get_issues_and_worklogs_in_range(session, start_date, end_date, client_text)
    issue_hours: dict[int, float] = defaultdict(float)
    for worklog in worklogs:
        issue_hours[worklog.issue_id] += worklog.time_spent_seconds / 3600
        
    matching_issue_ids = {issue.id for issue in issues}
    if normalized_client is not None:
        total_hours = round(sum(issue_hours.get(issue_id, 0.0) for issue_id in matching_issue_ids), 2)
    else:
        total_hours = round(sum(w.time_spent_seconds for w in worklogs) / 3600, 2)

    total_incidents = sum(
        1
        for issue in issues
        if issue.is_incident
        and issue.created_at_jira is not None
        and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date)
    )
    capacity_hours = expected_capacity_hours(start_date, end_date, settings.daily_hours)
    utilization = round((total_hours / capacity_hours * 100) if capacity_hours else 0, 2)
    return {
        "period": {"from": start_date.isoformat(), "to": end_date.isoformat()},
        "hours_logged": total_hours,
        "expected_capacity_hours": capacity_hours,
        "utilization_pct": utilization,
        "incidents": int(total_incidents),
        "business_days": len(business_days_between(start_date, end_date)),
    }


def build_daily_series(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> list[dict]:
    issues, rows = get_issues_and_worklogs_in_range(session, start_date, end_date, client_text)
    mapping: dict[str, float] = {}
    for row in rows:
        label = _date_label(row.started_at)
        mapping[label] = round(mapping.get(label, 0.0) + (row.time_spent_seconds / 3600), 2)
    return [{"label": day.isoformat(), "value": mapping.get(day.isoformat(), 0.0)} for day in business_days_between(start_date, end_date)]


def build_monthly_series(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> list[dict]:
    issues, rows = get_issues_and_worklogs_in_range(session, start_date, end_date, client_text)
    mapping: dict[str, float] = {}
    for row in rows:
        label = _month_label(row.started_at)
        mapping[label] = round(mapping.get(label, 0.0) + (row.time_spent_seconds / 3600), 2)
    return [{"label": label, "value": value} for label, value in sorted(mapping.items())]
def build_weekly_report(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> list[dict]:
    normalized_client = _normalize_client_filter(client_text)
    business_days = business_days_between(start_date, end_date)
    if not business_days:
        return []

    business_day_set = set(business_days)
    holiday_names_for_week = _holiday_names_for_week
    _, child_to_parent, _ = _build_subtask_maps(session)

    worklogs = session.scalars(
        select(JiraWorklog).options(selectinload(JiraWorklog.author_agent)).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()

    filtered_worklogs: list[tuple[JiraWorklog, date]] = []
    worklog_issue_ids: set[int] = set()
    for worklog in worklogs:
        local_dt = to_tz_aware(worklog.started_at, settings.app_timezone)
        if local_dt is None:
            continue
        local_date = local_dt.date()
        filtered_worklogs.append((worklog, local_date))
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        worklog_issue_ids.add(eff_id)

    issues = session.scalars(
        select(JiraIssue).where(
            or_(
                and_(
                    JiraIssue.created_at_jira.is_not(None),
                    JiraIssue.created_at_jira >= _range_start(start_date),
                    JiraIssue.created_at_jira <= _range_end(end_date),
                ),
                JiraIssue.id.in_(worklog_issue_ids) if worklog_issue_ids else False,
            )
        )
    ).all()
    
    issues = [issue for issue in issues if issue.id not in child_to_parent]
    
    if normalized_client is not None:
        issues = [issue for issue in issues if _issue_matches_client(issue, normalized_client)]

    issue_by_id = {issue.id: issue for issue in issues}
    
    mapped_filtered_worklogs = []
    for worklog, local_date in filtered_worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        if eff_id in issue_by_id:
            worklog.issue_id = eff_id
            mapped_filtered_worklogs.append((worklog, local_date))
    filtered_worklogs = mapped_filtered_worklogs

    week_buckets: dict[date, dict[str, object]] = {}
    for day in business_days:
        week_start = _week_start(day)
        bucket = week_buckets.setdefault(
            week_start,
            {
                "week_start": week_start,
                "week_end": week_start + timedelta(days=4),
                "business_days": [],
                "registered_ids": set(),
                "attended_ids": set(),
                "incident_ids": set(),
                "hours_logged": 0.0,
                "worklog_count": 0,
                "ticket_hours": defaultdict(float),
                "ticket_worklog_count": defaultdict(int),
                "client_hours": defaultdict(float),
                "agent_hours": defaultdict(float),
            },
        )
        bucket["business_days"].append(day)

    for issue in issues:
        created_at = to_tz_aware(issue.created_at_jira, settings.app_timezone)
        if created_at is None:
            continue
        created_date = created_at.date()
        if created_date not in business_day_set:
            continue
        week_start = _week_start(created_date)
        bucket = week_buckets.get(week_start)
        if bucket is None:
            continue
        bucket["registered_ids"].add(issue.id)
        if issue.is_incident:
            bucket["incident_ids"].add(issue.id)

    for worklog, local_date in filtered_worklogs:
        issue = issue_by_id.get(worklog.issue_id)
        if issue is None:
            continue
        week_start = _week_start(local_date)
        bucket = week_buckets.get(week_start)
        if bucket is None:
            continue
        hours = worklog.time_spent_seconds / 3600
        client_label = _issue_client_label(issue)
        agent_label = worklog.author_agent.name if worklog.author_agent else "Sin agente"
        
        service_level = _issue_service_level_label(issue).upper() if _issue_service_level_label(issue) else ""
        
        bucket["hours_logged"] = float(bucket.get("hours_logged", 0.0)) + hours
        if "L3" in service_level:
            bucket["hours_l3"] = float(bucket.get("hours_l3", 0.0)) + hours
        elif "L1" in service_level or "L2" in service_level:
            bucket["hours_l1_l2"] = float(bucket.get("hours_l1_l2", 0.0)) + hours
            
        bucket["worklog_count"] = int(bucket["worklog_count"]) + 1
        bucket["attended_ids"].add(issue.id)
        bucket["ticket_hours"][issue.id] += hours
        bucket["ticket_worklog_count"][issue.id] += 1
        bucket["client_hours"][client_label] += hours
        bucket["agent_hours"][agent_label] += hours

    result: list[dict] = []
    for week_start in sorted(week_buckets):
        bucket = week_buckets[week_start]
        week_days = bucket["business_days"]
        if not week_days:
            continue

        period_from = week_days[0]
        period_to = week_days[-1]
        hours_logged = round(float(bucket["hours_logged"]), 2)
        hours_l1_l2 = round(float(bucket.get("hours_l1_l2", 0.0)), 2)
        hours_l3 = round(float(bucket.get("hours_l3", 0.0)), 2)
        
        capacity_hours = float(len(week_days) * settings.daily_hours)
        utilization_pct = round((hours_l1_l2 / capacity_hours * 100) if capacity_hours else 0, 2)
        registered_count = len(bucket["registered_ids"])
        attended_count = len(bucket["attended_ids"])
        incident_count = len(bucket["incident_ids"])
        client_hours = bucket["client_hours"]
        agent_hours = bucket["agent_hours"]
        ticket_hours = bucket["ticket_hours"]
        ticket_worklog_count = bucket["ticket_worklog_count"]
        top_client = max(client_hours.items(), key=lambda item: (item[1], item[0].casefold()))[0] if client_hours else None
        top_agent = max(agent_hours.items(), key=lambda item: (item[1], item[0].casefold()))[0] if agent_hours else None
        top_tickets = []
        for issue_id, total_hours in sorted(ticket_hours.items(), key=lambda item: (-item[1], issue_by_id[item[0]].jira_key))[:3]:
            issue = issue_by_id.get(issue_id)
            if issue is None:
                continue
            top_tickets.append(
                {
                    "jira_key": issue.jira_key,
                    "summary": issue.summary,
                    "client_text": _issue_client_label(issue),
                    "service_level": _issue_service_level_label(issue),
                    "hours_logged": round(total_hours, 2),
                    "worklog_count": ticket_worklog_count.get(issue_id, 0),
                }
            )
        holiday_list = holiday_names_for_week(week_start, start_date, end_date)
        if hours_logged == 0 and registered_count == 0 and attended_count == 0:
            summary = (
                f"Semana del {_format_display_date(period_from)} al {_format_display_date(period_to)} sin actividad registrada "
                f"en días hábiles."
            )
        else:
            summary = (
                f"Semana del {_format_display_date(period_from)} al {_format_display_date(period_to)}: "
                f"{hours_logged:.2f} horas registradas en {len(week_days)} días hábiles "
                f"(capacidad {capacity_hours:.2f} h, utilización {utilization_pct:.2f}%). "
                f"{registered_count} tickets registrados, {attended_count} atendidos y {incident_count} incidencias."
            )
            if top_client:
                summary += f" Cliente con mayor consumo: {top_client}."
            if top_agent:
                summary += f" Agente con mayor carga: {top_agent}."
            if holiday_list:
                summary += f" Feriados omitidos: {', '.join(holiday_list)}."

        result.append(
            {
                "week_start": week_start.isoformat(),
                "week_end": (week_start + timedelta(days=4)).isoformat(),
                "period_from": period_from.isoformat(),
                "period_to": period_to.isoformat(),
                "label": f"{_format_display_date(period_from)} al {_format_display_date(period_to)}",
                "business_days": len(week_days),
                "hours_logged": hours_logged,
                "hours_l1_l2": round(float(bucket.get("hours_l1_l2", 0.0)), 2),
                "hours_l3": round(float(bucket.get("hours_l3", 0.0)), 2),
                "expected_capacity_hours": capacity_hours,
                "utilization_pct": utilization_pct,
                "tickets_registered": registered_count,
                "tickets_attended": attended_count,
                "incidents": incident_count,
                "holiday_names": holiday_list,
                "top_client": top_client,
                "top_agent": top_agent,
                "summary": summary,
                "top_tickets": top_tickets,
            }
        )

    return result


def build_agent_report(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> list[dict]:
    normalized_client = _normalize_client_filter(client_text)
    agents = session.scalars(select(Agent).where(Agent.active.is_(True)).order_by(Agent.name)).all()
    _, child_to_parent, _ = _build_subtask_maps(session)
    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issues = session.scalars(
        select(JiraIssue).options(selectinload(JiraIssue.organizations)).where(
            and_(
                JiraIssue.created_at_jira.is_not(None),
                JiraIssue.created_at_jira >= _range_start(start_date),
                JiraIssue.created_at_jira <= _range_end(end_date),
            )
        )
    ).all()
    
    issues = [issue for issue in issues if issue.id not in child_to_parent]
    
    for w in worklogs:
        if w.issue_id in child_to_parent:
            w.issue_id = child_to_parent[w.issue_id]
            
    if normalized_client is not None:
        issues = [issue for issue in issues if _issue_matches_client(issue, normalized_client)]
        matching_issue_ids = {issue.id for issue in issues}
        worklogs = [worklog for worklog in worklogs if worklog.issue_id in matching_issue_ids]
    result: list[dict] = []
    for agent in agents:
        hours = sum(w.time_spent_seconds for w in worklogs if w.author_agent_id == agent.id)
        incidents = sum(1 for issue in issues if issue.assignee_agent_id == agent.id and issue.is_incident)
        organizations = len({org.id for issue in issues if issue.assignee_agent_id == agent.id for org in issue.organizations})
        capacity = expected_capacity_hours(start_date, end_date, settings.daily_hours)
        hours_logged = round(hours / 3600, 2)
        result.append(
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "hours_logged": hours_logged,
                "capacity_hours": capacity,
                "utilization_pct": round((hours_logged / capacity * 100) if capacity else 0, 2),
                "incidents": int(incidents),
                "clients": int(organizations),
            }
        )
    return result


def build_agent_detail(
    session: Session,
    agent_id: int,
    start_date: date,
    end_date: date,
) -> dict:
    agent = session.scalar(select(Agent).where(Agent.id == agent_id))
    if agent is None:
        return {
            "agent_id": agent_id,
            "agent_name": "Agente no encontrado",
            "agent_email": None,
            "period_from": start_date.isoformat(),
            "period_to": end_date.isoformat(),
            "tickets_assigned": 0,
            "tickets_attended": 0,
            "tickets_with_hours": 0,
            "hours_logged": 0.0,
            "capacity_hours": 0.0,
            "utilization_pct": 0.0,
            "incident_count": 0,
            "tickets": [],
        }

    _, child_to_parent, id_to_key = _build_subtask_maps(session)
    
    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.author_agent_id == agent_id,
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()

    issue_worklogs: dict[int, list[JiraWorklog]] = defaultdict(list)
    issue_hours: dict[int, float] = defaultdict(float)
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_worklogs[eff_id].append(worklog)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600

    worklog_issue_ids = set(issue_worklogs.keys())
    
    issues = session.scalars(
        select(JiraIssue)
        .options(selectinload(JiraIssue.organizations), selectinload(JiraIssue.assignee_agent))
        .where(
            or_(
                and_(
                    JiraIssue.assignee_agent_id == agent_id,
                    JiraIssue.created_at_jira.is_not(None),
                    JiraIssue.created_at_jira >= _range_start(start_date),
                    JiraIssue.created_at_jira <= _range_end(end_date),
                ),
                JiraIssue.id.in_(worklog_issue_ids) if worklog_issue_ids else False,
            )
        )
    ).all()

    issues = [issue for issue in issues if issue.id not in child_to_parent]

    ticket_rows: list[dict] = []
    for issue in sorted(issues, key=lambda item: item.created_at_jira or datetime.min.replace(tzinfo=app_tz), reverse=True):
        ticket_rows.append(
            {
                "issue_id": issue.id,
                "jira_key": issue.jira_key,
                "organizations": [org.name for org in issue.organizations],
                "client_text": _issue_client_label(issue),
                "service_level": _issue_service_level_label(issue),
                "summary": issue.summary,
                "status": issue.status,
                "assignee_name": issue.assignee_agent.name if issue.assignee_agent else None,
                "created_at": issue.created_at_jira,
                "updated_at": issue.updated_at_jira,
                "resolved_at": issue.resolved_at_jira,
                "hours_logged": round(issue_hours.get(issue.id, 0.0), 2),
                "worklog_count": len(issue_worklogs.get(issue.id, [])),
                "incident": issue.is_incident,
                "worklogs": [
                    {
                        "worklog_id": w.jira_worklog_id,
                        "started_at": w.started_at,
                        "author_name": w.author_agent.name if w.author_agent else None,
                        "hours": round(w.time_spent_seconds / 3600, 2),
                        "comment": f"[{id_to_key.get(w.issue_id)}] {w.comment}" if w.issue_id != issue.id and w.comment else (f"[{id_to_key.get(w.issue_id)}]" if w.issue_id != issue.id else w.comment),
                    }
                    for w in sorted(issue_worklogs.get(issue.id, []), key=lambda item: item.started_at or datetime.min.replace(tzinfo=app_tz))
                ],
            }
        )

    capacity = expected_capacity_hours(start_date, end_date, settings.daily_hours)
    total_hours = round(sum(row["hours_logged"] for row in ticket_rows), 2)
    utilization = round((total_hours / capacity * 100) if capacity else 0, 2)
    
    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "agent_email": agent.email,
        "period_from": start_date.isoformat(),
        "period_to": end_date.isoformat(),
        "tickets_assigned": sum(1 for issue in ticket_rows if issue["assignee_name"] == agent.name),
        "tickets_attended": sum(1 for issue in ticket_rows if issue["worklog_count"] > 0),
        "tickets_with_hours": sum(1 for issue in ticket_rows if issue["hours_logged"] > 0),
        "hours_logged": total_hours,
        "capacity_hours": capacity,
        "utilization_pct": utilization,
        "incident_count": sum(1 for issue in ticket_rows if issue["incident"]),
        "tickets": ticket_rows,
    }


def _issue_has_org(issue: JiraIssue) -> bool:
    return len(issue.organizations) > 0


def build_organization_report(session: Session, start_date: date, end_date: date, client_text: str | None = None) -> list[dict]:
    normalized_client = _normalize_client_filter(client_text)
    _, child_to_parent, _ = _build_subtask_maps(session)
    organizations = session.scalars(
        select(Organization).options(selectinload(Organization.issues)).where(Organization.active.is_(True)).order_by(Organization.name)
    ).all()
    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issue_hours: dict[int, float] = defaultdict(float)
    issue_worklog_count: dict[int, int] = defaultdict(int)
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600
        issue_worklog_count[eff_id] += 1

    result: list[dict] = []
    for org in organizations:
        org_issues = [
            issue
            for issue in org.issues
            if issue.id not in child_to_parent
            and (
                (issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date))
                or issue.id in issue_hours
                or issue.id in issue_worklog_count
            )
        ]
        if normalized_client is not None:
            org_issues = [issue for issue in org_issues if _issue_matches_client(issue, normalized_client)]
        registered = [issue for issue in org_issues if issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date)]
        attended = [issue for issue in org_issues if issue_worklog_count.get(issue.id, 0) > 0]
        hours_logged = round(sum(issue_hours.get(issue.id, 0.0) for issue in org_issues), 2)
        result.append(
            {
                "organization_id": org.id,
                "organization_name": org.name,
                "tickets_registered": len(registered),
                "tickets_attended": len(attended),
                "hours_logged": hours_logged,
                "incidents": sum(1 for issue in org_issues if issue.is_incident),
            }
        )
    return result


def build_organization_detail(
    session: Session,
    organization_id: int,
    start_date: date,
    end_date: date,
    client_text: str | None = None,
) -> dict:
    org = session.scalar(select(Organization).options(selectinload(Organization.issues)).where(Organization.id == organization_id))
    if org is None:
        return {
            "organization_id": organization_id,
            "organization_name": "Organización no encontrada",
            "period_from": start_date.isoformat(),
            "period_to": end_date.isoformat(),
            "tickets_registered": 0,
            "tickets_attended": 0,
            "tickets_with_hours": 0,
            "hours_logged": 0.0,
            "incident_count": 0,
            "tickets": [],
        }

    _, child_to_parent, id_to_key = _build_subtask_maps(session)
    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issue_hours: dict[int, float] = defaultdict(float)
    issue_worklogs: dict[int, list[JiraWorklog]] = defaultdict(list)
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600
        issue_worklogs[eff_id].append(worklog)

    normalized_client = _normalize_client_filter(client_text)
    ticket_rows: list[dict] = []
    org_issues = [
        issue
        for issue in org.issues
        if issue.id not in child_to_parent
        and (
            (issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date))
            or issue.id in issue_hours
        )
    ]
    for issue in sorted(org_issues, key=lambda item: item.created_at_jira or datetime.min.replace(tzinfo=app_tz), reverse=True):
        ticket_client = _extract_client_text(issue)
        if normalized_client and _normalize_text(ticket_client) != normalized_client:
            continue
        ticket_rows.append(
            {
                "issue_id": issue.id,
                "jira_key": issue.jira_key,
                "organizations": [org.name for org in issue.organizations],
                "service_level": _issue_service_level_label(issue),
                "summary": issue.summary,
                "client_text": ticket_client,
                "status": issue.status,
                "assignee_name": issue.assignee_agent.name if issue.assignee_agent else None,
                "created_at": issue.created_at_jira,
                "updated_at": issue.updated_at_jira,
                "resolved_at": issue.resolved_at_jira,
                "hours_logged": round(issue_hours.get(issue.id, 0.0), 2),
                "worklog_count": len(issue_worklogs.get(issue.id, [])),
                "incident": issue.is_incident,
                "worklogs": [
                    {
                        "worklog_id": w.jira_worklog_id,
                        "started_at": w.started_at,
                        "author_name": w.author_agent.name if w.author_agent else None,
                        "hours": round(w.time_spent_seconds / 3600, 2),
                        "comment": f"[{id_to_key.get(w.issue_id)}] {w.comment}" if w.issue_id != issue.id and w.comment else (f"[{id_to_key.get(w.issue_id)}]" if w.issue_id != issue.id else w.comment),
                    }
                    for w in sorted(issue_worklogs.get(issue.id, []), key=lambda item: item.started_at or datetime.min.replace(tzinfo=app_tz))
                ],
            }
        )

    return {
        "organization_id": org.id,
        "organization_name": org.name,
        "client_filter": client_text,
        "period_from": start_date.isoformat(),
        "period_to": end_date.isoformat(),
        "tickets_registered": sum(1 for issue in ticket_rows if issue["created_at"] is not None and _range_start(start_date) <= issue["created_at"] <= _range_end(end_date)),
        "tickets_attended": sum(1 for issue in ticket_rows if issue["worklog_count"] > 0),
        "tickets_with_hours": sum(1 for issue in ticket_rows if issue["hours_logged"] > 0),
        "hours_logged": round(sum(issue["hours_logged"] for issue in ticket_rows), 2),
        "incident_count": sum(1 for issue in ticket_rows if issue["incident"]),
        "tickets": ticket_rows,
    }


def build_ticket_client_detail(
    session: Session,
    client_text: str,
    start_date: date,
    end_date: date,
) -> dict:
    normalized_client = _normalize_client_filter(client_text)
    if not normalized_client:
        return {
            "client_text": "",
            "client_key": "",
            "period_from": start_date.isoformat(),
            "period_to": end_date.isoformat(),
            "tickets_registered": 0,
            "tickets_attended": 0,
            "tickets_with_hours": 0,
            "hours_logged": 0.0,
            "incident_count": 0,
            "tickets": [],
        }

    _, child_to_parent, id_to_key = _build_subtask_maps(session)
    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issue_hours: dict[int, float] = defaultdict(float)
    issue_worklogs: dict[int, list[JiraWorklog]] = defaultdict(list)
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600
        issue_worklogs[eff_id].append(worklog)

    worklog_issue_ids = set(issue_worklogs.keys())
    issues = session.scalars(
        select(JiraIssue)
        .options(selectinload(JiraIssue.organizations), selectinload(JiraIssue.assignee_agent))
        .where(
            or_(
                and_(
                    JiraIssue.created_at_jira.is_not(None),
                    JiraIssue.created_at_jira >= _range_start(start_date),
                    JiraIssue.created_at_jira <= _range_end(end_date),
                ),
                JiraIssue.id.in_(worklog_issue_ids) if worklog_issue_ids else False,
            )
        )
    ).all()

    issues = [issue for issue in issues if issue.id not in child_to_parent]

    ticket_rows: list[dict] = []
    for issue in sorted(issues, key=lambda item: item.created_at_jira or datetime.min.replace(tzinfo=app_tz), reverse=True):
        ticket_client = _extract_client_text(issue)
        if _normalize_text(ticket_client) != normalized_client:
            continue
        ticket_rows.append(
            {
                "issue_id": issue.id,
                "jira_key": issue.jira_key,
                "organizations": [org.name for org in issue.organizations],
                "service_level": _issue_service_level_label(issue),
                "summary": issue.summary,
                "client_text": ticket_client,
                "status": issue.status,
                "assignee_name": issue.assignee_agent.name if issue.assignee_agent else None,
                "created_at": issue.created_at_jira,
                "updated_at": issue.updated_at_jira,
                "resolved_at": issue.resolved_at_jira,
                "hours_logged": round(issue_hours.get(issue.id, 0.0), 2),
                "worklog_count": len(issue_worklogs.get(issue.id, [])),
                "incident": issue.is_incident,
                "worklogs": [
                    {
                        "worklog_id": w.jira_worklog_id,
                        "started_at": w.started_at,
                        "author_name": w.author_agent.name if w.author_agent else None,
                        "hours": round(w.time_spent_seconds / 3600, 2),
                        "comment": f"[{id_to_key.get(w.issue_id)}] {w.comment}" if w.issue_id != issue.id and w.comment else (f"[{id_to_key.get(w.issue_id)}]" if w.issue_id != issue.id else w.comment),
                    }
                    for w in sorted(issue_worklogs.get(issue.id, []), key=lambda item: item.started_at or datetime.min.replace(tzinfo=app_tz))
                ],
            }
        )

    display_text = ticket_rows[0]["client_text"] if ticket_rows else client_text
    return {
        "client_text": display_text or client_text,
        "client_key": normalized_client,
        "period_from": start_date.isoformat(),
        "period_to": end_date.isoformat(),
        "tickets_registered": sum(1 for issue in ticket_rows if issue["created_at"] is not None and _range_start(start_date) <= issue["created_at"] <= _range_end(end_date)),
        "tickets_attended": sum(1 for issue in ticket_rows if issue["worklog_count"] > 0),
        "tickets_with_hours": sum(1 for issue in ticket_rows if issue["hours_logged"] > 0),
        "hours_logged": round(sum(issue["hours_logged"] for issue in ticket_rows), 2),
        "incident_count": sum(1 for issue in ticket_rows if issue["incident"]),
        "tickets": ticket_rows,
    }


def _client_issue_window(session: Session, start_date: date, end_date: date) -> list[JiraIssue]:
    return session.scalars(
        select(JiraIssue).where(
            and_(
                JiraIssue.reporter_client_id.is_not(None),
                JiraIssue.created_at_jira.is_not(None),
                JiraIssue.created_at_jira >= _range_start(start_date),
                JiraIssue.created_at_jira <= _range_end(end_date),
            )
        )
    ).all()


def _client_activity_issues(session: Session, start_date: date, end_date: date) -> list[JiraIssue]:
    issues = session.scalars(
        select(JiraIssue).where(JiraIssue.reporter_client_id.is_not(None))
    ).all()
    worklog_issue_ids = {
        row.issue_id
        for row in session.scalars(
            select(JiraWorklog).where(
                and_(
                    JiraWorklog.started_at.is_not(None),
                    JiraWorklog.started_at >= _range_start(start_date),
                    JiraWorklog.started_at <= _range_end(end_date),
                )
            )
        ).all()
    }
    return [
        issue
        for issue in issues
        if (
            (issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date))
            or issue.id in worklog_issue_ids
        )
    ]


def build_client_report(session: Session, start_date: date, end_date: date) -> list[dict]:
    clients = session.scalars(select(Client).where(Client.active.is_(True)).order_by(Client.name)).all()
    _, child_to_parent, _ = _build_subtask_maps(session)
    registered_issues = _client_issue_window(session, start_date, end_date)
    activity_issues = _client_activity_issues(session, start_date, end_date)
    
    registered_issues = [issue for issue in registered_issues if issue.id not in child_to_parent]
    activity_issues = [issue for issue in activity_issues if issue.id not in child_to_parent]

    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issue_hours: dict[int, float] = defaultdict(float)
    issue_worklogs: dict[int, int] = defaultdict(int)
    issue_incident: dict[int, bool] = {}
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600
        issue_worklogs[eff_id] += 1
    for issue in activity_issues:
        issue_incident[issue.id] = issue.is_incident

    result: list[dict] = []
    for client in clients:
        client_registered = [issue for issue in registered_issues if issue.reporter_client_id == client.id]
        client_activity = [issue for issue in activity_issues if issue.reporter_client_id == client.id]
        hours_logged = round(sum(issue_hours.get(issue.id, 0.0) for issue in client_activity), 2)
        incidents = sum(1 for issue in client_activity if issue.is_incident)
        result.append(
            {
                "client_id": client.id,
                "client_name": client.name,
                "client_email": client.email,
                "tickets_registered": len(client_registered),
                "tickets_attended": sum(1 for issue in client_activity if issue_worklogs.get(issue.id, 0) > 0),
                "hours_logged": hours_logged,
                "incidents": incidents,
            }
        )
    return result


def build_client_detail(session: Session, client_id: int, start_date: date, end_date: date) -> dict:
    client = session.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        return {
            "client_id": client_id,
            "client_name": "Cliente no encontrado",
            "client_email": None,
            "period_from": start_date.isoformat(),
            "period_to": end_date.isoformat(),
            "tickets_registered": 0,
            "tickets_attended": 0,
            "tickets_with_hours": 0,
            "hours_logged": 0.0,
            "incident_count": 0,
            "tickets": [],
        }

    _, child_to_parent, id_to_key = _build_subtask_maps(session)
    registered_issues = session.scalars(
        select(JiraIssue).where(
            and_(
                JiraIssue.reporter_client_id == client_id,
                JiraIssue.created_at_jira.is_not(None),
                JiraIssue.created_at_jira >= _range_start(start_date),
                JiraIssue.created_at_jira <= _range_end(end_date),
            )
        )
    ).all()
    activity_issues = session.scalars(
        select(JiraIssue).where(JiraIssue.reporter_client_id == client_id)
    ).all()
    
    registered_issues = [issue for issue in registered_issues if issue.id not in child_to_parent]
    activity_issues = [issue for issue in activity_issues if issue.id not in child_to_parent]

    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()

    issue_worklogs: dict[int, list[JiraWorklog]] = defaultdict(list)
    issue_hours: dict[int, float] = defaultdict(float)
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_worklogs[eff_id].append(worklog)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600

    ticket_rows: list[dict] = []
    seen_issue_ids: set[int] = set()
    for issue in activity_issues:
        if issue.id in seen_issue_ids:
            continue
        issue_has_range_activity = (
            (issue.created_at_jira is not None and _range_start(start_date) <= issue.created_at_jira <= _range_end(end_date))
            or len(issue_worklogs.get(issue.id, [])) > 0
        )
        if not issue_has_range_activity:
            continue
        seen_issue_ids.add(issue.id)
        assignee_name = issue.assignee_agent.name if issue.assignee_agent else None
        ticket_rows.append(
            {
                "issue_id": issue.id,
                "jira_key": issue.jira_key,
                "organizations": [org.name for org in issue.organizations],
                "client_text": _extract_client_text(issue) or client.name,
                "service_level": _issue_service_level_label(issue),
                "summary": issue.summary,
                "status": issue.status,
                "assignee_name": assignee_name,
                "created_at": issue.created_at_jira,
                "updated_at": issue.updated_at_jira,
                "resolved_at": issue.resolved_at_jira,
                "hours_logged": round(issue_hours.get(issue.id, 0.0), 2),
                "worklog_count": len(issue_worklogs.get(issue.id, [])),
                "incident": issue.is_incident,
                "worklogs": [
                    {
                        "worklog_id": w.jira_worklog_id,
                        "started_at": w.started_at,
                        "author_name": w.author_agent.name if w.author_agent else None,
                        "hours": round(w.time_spent_seconds / 3600, 2),
                        "comment": f"[{id_to_key.get(w.issue_id)}] {w.comment}" if w.issue_id != issue.id and w.comment else (f"[{id_to_key.get(w.issue_id)}]" if w.issue_id != issue.id else w.comment),
                    }
                    for w in sorted(issue_worklogs.get(issue.id, []), key=lambda item: item.started_at or datetime.min.replace(tzinfo=app_tz))
                ],
            }
        )

    ticket_rows.sort(key=lambda item: (item["created_at"] or datetime.min.replace(tzinfo=app_tz)), reverse=True)
    hours_logged = round(sum(row["hours_logged"] for row in ticket_rows), 2)
    return {
        "client_id": client.id,
        "client_name": client.name,
        "client_email": client.email,
        "period_from": start_date.isoformat(),
        "period_to": end_date.isoformat(),
        "tickets_registered": len(registered_issues),
        "tickets_attended": sum(1 for issue in ticket_rows if issue["worklog_count"] > 0),
        "tickets_with_hours": sum(1 for issue in ticket_rows if issue["hours_logged"] > 0),
        "hours_logged": hours_logged,
        "incident_count": sum(1 for issue in ticket_rows if issue["incident"]),
        "tickets": ticket_rows,
    }


def build_tickets_report(
    session: Session,
    start_date: date,
    end_date: date,
    client_text: str | None = None,
    status: str | None = None,
    service_level: str | None = None,
) -> list[dict]:
    normalized_client = _normalize_client_filter(client_text)
    normalized_level = _normalize_text(service_level) if service_level else None
    _, child_to_parent, id_to_key = _build_subtask_maps(session)

    worklogs = session.scalars(
        select(JiraWorklog).where(
            and_(
                JiraWorklog.started_at.is_not(None),
                JiraWorklog.started_at >= _range_start(start_date),
                JiraWorklog.started_at <= _range_end(end_date),
            )
        )
    ).all()
    issue_hours: dict[int, float] = defaultdict(float)
    issue_worklogs: dict[int, list[JiraWorklog]] = defaultdict(list)
    for worklog in worklogs:
        eff_id = child_to_parent.get(worklog.issue_id, worklog.issue_id)
        issue_hours[eff_id] += worklog.time_spent_seconds / 3600
        issue_worklogs[eff_id].append(worklog)

    worklog_issue_ids = set(issue_worklogs.keys())
    
    issues = session.scalars(
        select(JiraIssue)
        .options(selectinload(JiraIssue.organizations), selectinload(JiraIssue.assignee_agent))
        .where(
            or_(
                and_(
                    JiraIssue.created_at_jira.is_not(None),
                    JiraIssue.created_at_jira >= _range_start(start_date),
                    JiraIssue.created_at_jira <= _range_end(end_date),
                ),
                JiraIssue.id.in_(worklog_issue_ids) if worklog_issue_ids else False,
            )
        )
    ).all()

    issues = [issue for issue in issues if issue.id not in child_to_parent]

    ticket_rows: list[dict] = []
    for issue in sorted(issues, key=lambda item: item.created_at_jira or datetime.min.replace(tzinfo=app_tz), reverse=True):
        ticket_client = _extract_client_text(issue)
        if normalized_client and _normalize_text(ticket_client) != normalized_client:
            continue
            
        if status and issue.status.casefold() != status.casefold():
            continue
            
        issue_service_level = _issue_service_level_label(issue)
        if normalized_level and _normalize_text(issue_service_level) != normalized_level:
            continue
            
        ticket_rows.append(
            {
                "issue_id": issue.id,
                "jira_key": issue.jira_key,
                "organizations": [org.name for org in issue.organizations],
                "service_level": issue_service_level,
                "summary": issue.summary,
                "client_text": ticket_client,
                "status": issue.status,
                "assignee_name": issue.assignee_agent.name if issue.assignee_agent else None,
                "created_at": issue.created_at_jira,
                "updated_at": issue.updated_at_jira,
                "resolved_at": issue.resolved_at_jira,
                "hours_logged": round(issue_hours.get(issue.id, 0.0), 2),
                "worklog_count": len(issue_worklogs.get(issue.id, [])),
                "incident": issue.is_incident,
                "worklogs": [
                    {
                        "worklog_id": w.jira_worklog_id,
                        "started_at": w.started_at,
                        "author_name": w.author_agent.name if w.author_agent else None,
                        "hours": round(w.time_spent_seconds / 3600, 2),
                        "comment": f"[{id_to_key.get(w.issue_id)}] {w.comment}" if w.issue_id != issue.id and w.comment else (f"[{id_to_key.get(w.issue_id)}]" if w.issue_id != issue.id else w.comment),
                    }
                    for w in sorted(issue_worklogs.get(issue.id, []), key=lambda item: item.started_at or datetime.min.replace(tzinfo=app_tz))
                ],
            }
        )

    return ticket_rows


def build_clients_export_data(session: Session) -> list[dict]:
    stmt = select(Client).options(
        selectinload(Client.issues_reported).selectinload(JiraIssue.organizations)
    ).order_by(Client.name)

    clients = session.scalars(stmt).all()

    rows: list[dict] = []
    for c in clients:
        email = c.email
        if not email and c.name and "@" in c.name:
            email = c.name

        companies = set()
        for issue in c.issues_reported:
            comp = _extract_client_text(issue)
            if comp:
                companies.add(comp)
            for org in issue.organizations:
                if org.name:
                    companies.add(org.name)

        seen_normalized = set()
        unique_companies = []
        for comp in sorted(companies, key=lambda x: (x.lower(), x)):
            norm = comp.strip().lower()
            if norm not in seen_normalized:
                seen_normalized.add(norm)
                unique_companies.append(comp.strip())

        company_str = ", ".join(unique_companies)

        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "email": email or "",
                "company": company_str,
                "ticket_count": len(c.issues_reported),
                "jira_account_id": c.jira_account_id or "",
                "active": "Sí" if c.active else "No",
            }
        )

    # Check for informers that might not be in clients table
    informers = session.scalars(select(CompanyInformer).options(selectinload(CompanyInformer.company))).all()
    for inf in informers:
        existing = next(
            (
                r
                for r in rows
                if (inf.jira_account_id and r["jira_account_id"] == inf.jira_account_id)
                or (inf.email and r["email"] and r["email"].lower() == inf.email.lower())
            ),
            None,
        )
        if existing:
            if inf.company and inf.company.name:
                if existing["company"]:
                    if inf.company.name.lower() not in existing["company"].lower():
                        existing["company"] += f", {inf.company.name}"
                else:
                    existing["company"] = inf.company.name
        else:
            rows.append(
                {
                    "id": f"INF-{inf.id}",
                    "name": inf.name,
                    "email": inf.email or "",
                    "company": inf.company.name if inf.company else "",
                    "ticket_count": 0,
                    "jira_account_id": inf.jira_account_id or "",
                    "active": "Sí" if inf.active else "No",
                }
            )

    return rows


def get_distinct_issue_statuses(session: Session) -> list[str]:
    statuses = session.scalars(select(JiraIssue.status).distinct()).all()
    cleaned = sorted({s.strip() for s in statuses if s and s.strip()})
    return cleaned


def build_hours_consumption_report(
    session: Session,
    start_date: date,
    end_date: date,
    client_text: str | None = None,
    agent_id: int | None = None,
    service_level: str | None = None,
    statuses: list[str] | None = None,
) -> dict:
    issues, worklogs = get_issues_and_worklogs_in_range(session, start_date, end_date, client_text=client_text)
    issue_map = {i.id: i for i in issues}

    # Filtrar worklogs por agente si se especifica
    if agent_id is not None:
        worklogs = [w for w in worklogs if w.author_agent_id == agent_id]

    # Filtrar por nivel de servicio si se especifica
    if service_level is not None and service_level.strip():
        norm_sl = service_level.strip().upper()
        valid_issue_ids = {
            i.id for i in issues if _issue_service_level_label(i).upper() == norm_sl or norm_sl in _issue_service_level_label(i).upper()
        }
        worklogs = [w for w in worklogs if w.issue_id in valid_issue_ids]

    # Filtrar por múltiples estados si se especifican
    if statuses:
        norm_statuses = {s.strip().casefold() for s in statuses if s and s.strip()}
        if norm_statuses:
            valid_issue_ids = {
                i.id for i in issues if i.status and i.status.strip().casefold() in norm_statuses
            }
            worklogs = [w for w in worklogs if w.issue_id in valid_issue_ids]

    total_seconds = sum(w.time_spent_seconds for w in worklogs)
    total_hours = round(total_seconds / 3600.0, 2)
    total_worklogs = len(worklogs)

    # Mapear worklogs a tickets
    ticket_worklogs = defaultdict(list)
    for w in worklogs:
        ticket_worklogs[w.issue_id].append(w)

    total_tickets = len(ticket_worklogs)
    avg_hours = round(total_hours / total_tickets, 2) if total_tickets > 0 else 0.0

    # Desglose por cliente
    client_hours = defaultdict(float)
    client_ticket_ids = defaultdict(set)
    for issue_id, w_list in ticket_worklogs.items():
        issue = issue_map.get(issue_id)
        c_label = _issue_client_label(issue) if issue else "Sin cliente"
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        client_hours[c_label] += hrs
        client_ticket_ids[c_label].add(issue_id)

    client_rows = []
    for c_label, hrs in sorted(client_hours.items(), key=lambda x: x[1], reverse=True):
        pct = round((hrs / total_hours * 100), 1) if total_hours > 0 else 0.0
        client_rows.append({
            "client_name": c_label,
            "hours_logged": round(hrs, 2),
            "ticket_count": len(client_ticket_ids[c_label]),
            "percentage": pct,
        })

    top_client_name = client_rows[0]["client_name"] if client_rows else None
    top_client_hours = client_rows[0]["hours_logged"] if client_rows else 0.0

    # Desglose por agente
    agent_hours = defaultdict(float)
    agent_ticket_ids = defaultdict(set)
    agent_names = {}
    for w in worklogs:
        ag_id = w.author_agent_id
        ag_name = w.author_agent.name if w.author_agent else "Sin asignar"
        key = ag_id if ag_id is not None else ag_name
        agent_names[key] = ag_name
        hrs = w.time_spent_seconds / 3600.0
        agent_hours[key] += hrs
        agent_ticket_ids[key].add(w.issue_id)

    agent_rows = []
    for key, hrs in sorted(agent_hours.items(), key=lambda x: x[1], reverse=True):
        pct = round((hrs / total_hours * 100), 1) if total_hours > 0 else 0.0
        ag_id = key if isinstance(key, int) else None
        agent_rows.append({
            "agent_id": ag_id,
            "agent_name": agent_names[key],
            "hours_logged": round(hrs, 2),
            "ticket_count": len(agent_ticket_ids[key]),
            "percentage": pct,
        })

    top_agent_name = agent_rows[0]["agent_name"] if agent_rows else None
    top_agent_hours = agent_rows[0]["hours_logged"] if agent_rows else 0.0

    # Desglose por nivel de servicio
    sl_hours = defaultdict(float)
    sl_ticket_ids = defaultdict(set)
    for issue_id, w_list in ticket_worklogs.items():
        issue = issue_map.get(issue_id)
        sl_label = _issue_service_level_label(issue) if issue else "Sin nivel"
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        sl_hours[sl_label] += hrs
        sl_ticket_ids[sl_label].add(issue_id)

    sl_rows = []
    for sl_label, hrs in sorted(sl_hours.items(), key=lambda x: x[1], reverse=True):
        pct = round((hrs / total_hours * 100), 1) if total_hours > 0 else 0.0
        sl_rows.append({
            "service_level": sl_label,
            "hours_logged": round(hrs, 2),
            "ticket_count": len(sl_ticket_ids[sl_label]),
            "percentage": pct,
        })

    # Desglose por estado de ticket
    status_hours = defaultdict(float)
    status_ticket_ids = defaultdict(set)
    for issue_id, w_list in ticket_worklogs.items():
        issue = issue_map.get(issue_id)
        st_label = issue.status if (issue and issue.status) else "Sin estado"
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        status_hours[st_label] += hrs
        status_ticket_ids[st_label].add(issue_id)

    status_rows = []
    for st_label, hrs in sorted(status_hours.items(), key=lambda x: x[1], reverse=True):
        pct = round((hrs / total_hours * 100), 1) if total_hours > 0 else 0.0
        status_rows.append({
            "status_name": st_label,
            "hours_logged": round(hrs, 2),
            "ticket_count": len(status_ticket_ids[st_label]),
            "percentage": pct,
        })

    # Desglose por ticket
    ticket_rows = []
    for issue_id, w_list in ticket_worklogs.items():
        issue = issue_map.get(issue_id)
        if not issue:
            continue
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        c_label = _issue_client_label(issue)
        sl_label = _issue_service_level_label(issue)
        ag_name = issue.assignee_agent.name if issue.assignee_agent else (w_list[0].author_agent.name if w_list and w_list[0].author_agent else "Sin asignar")
        ticket_rows.append({
            "jira_key": issue.jira_key,
            "summary": issue.summary,
            "client_name": c_label,
            "agent_name": ag_name,
            "service_level": sl_label,
            "hours_logged": round(hrs, 2),
            "worklog_count": len(w_list),
        })

    ticket_rows.sort(key=lambda x: x["hours_logged"], reverse=True)

    # Serie temporal diaria
    daily_map = defaultdict(float)
    for w in worklogs:
        d_str = _date_label(w.started_at)
        daily_map[d_str] += w.time_spent_seconds / 3600.0

    daily_series = []
    curr = start_date
    while curr <= end_date:
        d_str = curr.isoformat()
        daily_series.append({
            "date": d_str,
            "hours": round(daily_map.get(d_str, 0.0), 2),
        })
        curr += timedelta(days=1)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "kpis": {
            "total_hours": total_hours,
            "total_worklogs": total_worklogs,
            "total_tickets": total_tickets,
            "avg_hours_per_ticket": avg_hours,
            "top_client_name": top_client_name,
            "top_client_hours": top_client_hours,
            "top_agent_name": top_agent_name,
            "top_agent_hours": top_agent_hours,
        },
        "clients": client_rows,
        "agents": agent_rows,
        "service_levels": sl_rows,
        "statuses": status_rows,
        "tickets": ticket_rows,
        "daily_series": daily_series,
    }


def _is_issue_visit(issue: JiraIssue) -> tuple[bool, str]:
    """Devuelve (is_visit, visit_type) donde visit_type es 'Visita Programada' o 'Visita No Programada'."""
    fields = (issue.raw_payload or {}).get("fields") or {}
    ta = fields.get(get_settings().jira_tipo_atencion_field_id)
    
    is_visita = False
    is_programada = True
    
    if isinstance(ta, dict):
        val = ta.get("value")
        opt_id = str(ta.get("id"))
        if val == "Visita Programada" or opt_id == "10406":
            is_visita = True
            is_programada = True
        elif val == "Visita No Programada" or opt_id == "10407" or (val and "no programada" in str(val).lower()):
            is_visita = True
            is_programada = False
    elif isinstance(ta, str):
        if ta == "Visita Programada" or ta == "10406":
            is_visita = True
            is_programada = True
        elif ta == "Visita No Programada" or ta == "10407" or "no programada" in ta.lower():
            is_visita = True
            is_programada = False

    summary = (issue.summary or "").lower()
    if not is_visita and ("visita" in summary or "terreno" in summary):
        is_visita = True
        if "no programada" in summary or "emergencia" in summary or "imprevista" in summary:
            is_programada = False
        else:
            is_programada = True

    if not is_visita:
        return False, "Sin Clasificar"

    return True, "Visita Programada" if is_programada else "Visita No Programada"


def build_visits_report(
    session: Session,
    start_date: date,
    end_date: date,
    client_text: str | None = None,
    agent_id: int | None = None,
    visit_type: str | None = None,
) -> dict:
    issues, worklogs = get_issues_and_worklogs_in_range(session, start_date, end_date, client_text=client_text)
    issue_map = {i.id: i for i in issues}

    # Identificar tickets que son visitas
    visit_issue_map = {}
    for issue in issues:
        is_v, v_type = _is_issue_visit(issue)
        if is_v:
            visit_issue_map[issue.id] = (issue, v_type)

    # Filtrar por agente si se especifica
    if agent_id is not None:
        worklogs = [w for w in worklogs if w.author_agent_id == agent_id]

    # Filtrar worklogs e issues pertenecientes a visitas
    visit_worklogs = [w for w in worklogs if w.issue_id in visit_issue_map]

    # Filtrar por tipo de visita si se especifica
    if visit_type and visit_type.strip():
        norm_vt = visit_type.strip().lower()
        valid_issue_ids = {
            i_id for i_id, (_, vt) in visit_issue_map.items() if norm_vt in vt.lower()
        }
        visit_worklogs = [w for w in visit_worklogs if w.issue_id in valid_issue_ids]
        visit_issue_map = {k: v for k, v in visit_issue_map.items() if k in valid_issue_ids}

    # Mapear worklogs a tickets de visita
    ticket_worklogs = defaultdict(list)
    for w in visit_worklogs:
        ticket_worklogs[w.issue_id].append(w)

    active_visit_issues = {}
    for i_id, (issue, v_type) in visit_issue_map.items():
        if i_id in ticket_worklogs or not visit_worklogs:
            active_visit_issues[i_id] = (issue, v_type)

    total_seconds = sum(w.time_spent_seconds for w in visit_worklogs)
    total_hours = round(total_seconds / 3600.0, 2)

    scheduled_count = sum(1 for _, (_, vt) in active_visit_issues.items() if vt == "Visita Programada")
    unscheduled_count = sum(1 for _, (_, vt) in active_visit_issues.items() if vt == "Visita No Programada")
    total_visits = len(active_visit_issues)
    avg_hours = round(total_hours / total_visits, 2) if total_visits > 0 else 0.0

    # Desglose por tipo de visita
    type_hours = defaultdict(float)
    type_counts = defaultdict(int)
    for i_id, (issue, v_type) in active_visit_issues.items():
        w_list = ticket_worklogs.get(i_id, [])
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        type_hours[v_type] += hrs
        type_counts[v_type] += 1

    type_rows = []
    for vt_name in ["Visita Programada", "Visita No Programada"]:
        cnt = type_counts.get(vt_name, 0)
        hrs = type_hours.get(vt_name, 0.0)
        pct = round((hrs / total_hours * 100), 1) if total_hours > 0 else 0.0
        type_rows.append({
            "visit_type": vt_name,
            "visit_count": cnt,
            "hours_logged": round(hrs, 2),
            "percentage": pct,
        })

    # Desglose por cliente
    client_hours = defaultdict(float)
    client_sched = defaultdict(int)
    client_unsched = defaultdict(int)
    for i_id, (issue, v_type) in active_visit_issues.items():
        c_label = _issue_client_label(issue)
        w_list = ticket_worklogs.get(i_id, [])
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        client_hours[c_label] += hrs
        if v_type == "Visita Programada":
            client_sched[c_label] += 1
        else:
            client_unsched[c_label] += 1

    client_rows = []
    all_clients = set(client_sched.keys()) | set(client_unsched.keys())
    for c_label in all_clients:
        sch = client_sched[c_label]
        unsch = client_unsched[c_label]
        tot = sch + unsch
        hrs = client_hours[c_label]
        client_rows.append({
            "client_name": c_label,
            "scheduled_count": sch,
            "unscheduled_count": unsch,
            "total_visits": tot,
            "hours_logged": round(hrs, 2),
        })
    client_rows.sort(key=lambda x: x["total_visits"], reverse=True)

    top_client_name = client_rows[0]["client_name"] if client_rows else None
    top_client_visits = client_rows[0]["total_visits"] if client_rows else 0

    # Desglose por agente
    agent_hours = defaultdict(float)
    agent_sched = defaultdict(int)
    agent_unsched = defaultdict(int)
    agent_names = {}

    for i_id, (issue, v_type) in active_visit_issues.items():
        ag_name = issue.assignee_agent.name if issue.assignee_agent else "Sin asignar"
        ag_id = issue.assignee_agent_id
        key = ag_id if ag_id is not None else ag_name
        agent_names[key] = ag_name

        w_list = ticket_worklogs.get(i_id, [])
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        agent_hours[key] += hrs
        if v_type == "Visita Programada":
            agent_sched[key] += 1
        else:
            agent_unsched[key] += 1

    agent_rows = []
    all_agents = set(agent_sched.keys()) | set(agent_unsched.keys())
    for key in all_agents:
        ag_id = key if isinstance(key, int) else None
        sch = agent_sched[key]
        unsch = agent_unsched[key]
        tot = sch + unsch
        hrs = agent_hours[key]
        agent_rows.append({
            "agent_id": ag_id,
            "agent_name": agent_names[key],
            "scheduled_count": sch,
            "unscheduled_count": unsch,
            "total_visits": tot,
            "hours_logged": round(hrs, 2),
        })
    agent_rows.sort(key=lambda x: x["total_visits"], reverse=True)

    # Detalle por ticket
    ticket_rows = []
    for i_id, (issue, v_type) in active_visit_issues.items():
        w_list = ticket_worklogs.get(i_id, [])
        hrs = sum(w.time_spent_seconds for w in w_list) / 3600.0
        c_label = _issue_client_label(issue)
        ag_name = issue.assignee_agent.name if issue.assignee_agent else "Sin asignar"
        v_date = issue.created_at_jira.strftime("%Y-%m-%d") if issue.created_at_jira else start_date.isoformat()
        ticket_rows.append({
            "jira_key": issue.jira_key,
            "summary": issue.summary,
            "client_name": c_label,
            "agent_name": ag_name,
            "visit_type": v_type,
            "visit_date": v_date,
            "hours_logged": round(hrs, 2),
            "status": issue.status or "Abierto",
        })
    ticket_rows.sort(key=lambda x: x["visit_date"], reverse=True)

    # Serie temporal diaria
    daily_sched = defaultdict(int)
    daily_unsched = defaultdict(int)
    for i_id, (issue, v_type) in active_visit_issues.items():
        d_str = issue.created_at_jira.strftime("%Y-%m-%d") if issue.created_at_jira else start_date.isoformat()
        if v_type == "Visita Programada":
            daily_sched[d_str] += 1
        else:
            daily_unsched[d_str] += 1

    daily_series = []
    curr = start_date
    while curr <= end_date:
        d_str = curr.isoformat()
        sch = daily_sched.get(d_str, 0)
        unsch = daily_unsched.get(d_str, 0)
        daily_series.append({
            "date": d_str,
            "scheduled_count": sch,
            "unscheduled_count": unsch,
            "total_visits": sch + unsch,
        })
        curr += timedelta(days=1)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "kpis": {
            "total_visits": total_visits,
            "scheduled_visits": scheduled_count,
            "unscheduled_visits": unscheduled_count,
            "total_hours": total_hours,
            "avg_hours_per_visit": avg_hours,
            "top_client_name": top_client_name,
            "top_client_visits": top_client_visits,
        },
        "types": type_rows,
        "clients": client_rows,
        "agents": agent_rows,
        "tickets": ticket_rows,
        "daily_series": daily_series,
    }
