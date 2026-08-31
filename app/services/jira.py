from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
from dateutil import parser as date_parser


@dataclass
class JiraUser:
    account_id: str | None
    display_name: str
    email: str | None = None


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def search_issues(
        self,
        jql: str,
        max_results: int = 50,
        next_page_token: str | None = None,
        extra_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/rest/api/3/search/jql"
        fields = [
            "summary",
            "issuetype",
            "status",
            "priority",
            "project",
            "assignee",
            "reporter",
            "created",
            "updated",
            "resolutiondate",
            "subtasks",
            "parent",
        ]
        for field in extra_fields or []:
            if field and field not in fields:
                fields.append(field)
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ",".join(fields),
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token
        response = self.session.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def list_organizations(self, start: int = 0, limit: int = 50) -> dict[str, Any]:
        url = f"{self.base_url}/rest/servicedeskapi/organization"
        params = {"start": start, "limit": limit}
        response = self.session.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def get_issue_worklogs(self, issue_key: str) -> dict[str, Any]:
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}/worklog"
        params = {"maxResults": 1000}
        response = self.session.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def create_issue(self, fields: dict[str, Any], update: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/rest/api/3/issue"
        params = {"overrideScreenSecurity": "true", "overrideEditableFlag": "true"}
        payload = {"fields": fields}
        if update:
            payload["update"] = update
        response = self.session.post(url, json=payload, params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def update_issue(self, issue_key: str, fields: dict[str, Any], update: dict[str, Any] | None = None) -> None:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        params = {"overrideScreenSecurity": "true", "overrideEditableFlag": "true"}
        payload = {"fields": fields}
        if update:
            payload["update"] = update
        response = self.session.put(url, json=payload, params=params, timeout=60)
        response.raise_for_status()


def parse_jira_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return date_parser.isoparse(value)


def jira_user_to_dict(user: dict[str, Any] | None) -> JiraUser | None:
    if not user:
        return None
    return JiraUser(
        account_id=user.get("accountId"),
        display_name=user.get("displayName") or user.get("name") or "Sin nombre",
        email=user.get("emailAddress"),
    )
