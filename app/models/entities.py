from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Table, Text, UniqueConstraint, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jira_account_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    issues_reported: Mapped[list["JiraIssue"]] = relationship(back_populates="reporter_client")


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jira_organization_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    issues: Mapped[list["JiraIssue"]] = relationship(
        secondary=lambda: issue_organizations,
        back_populates="organizations",
    )


issue_organizations = Table(
    "issue_organizations",
    Base.metadata,
    Column("issue_id", ForeignKey("jira_issues.id"), primary_key=True),
    Column("organization_id", ForeignKey("organizations.id"), primary_key=True),
)


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jira_account_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    assigned_issues: Mapped[list["JiraIssue"]] = relationship(back_populates="assignee_agent")
    worklogs: Mapped[list["JiraWorklog"]] = relationship(back_populates="author_agent")


class JiraIssue(Base, TimestampMixin):
    __tablename__ = "jira_issues"
    __table_args__ = (UniqueConstraint("jira_id", name="uq_jira_issue_jira_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jira_id: Mapped[str] = mapped_column(String(64), nullable=False)
    jira_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    project_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    issue_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    priority: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_incident: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at_jira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_jira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolved_at_jira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    reporter_client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    assignee_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)

    reporter_client: Mapped["Client | None"] = relationship(back_populates="issues_reported")
    assignee_agent: Mapped["Agent | None"] = relationship(back_populates="assigned_issues")
    organizations: Mapped[list["Organization"]] = relationship(
        secondary=issue_organizations,
        back_populates="issues",
    )
    worklogs: Mapped[list["JiraWorklog"]] = relationship(back_populates="issue", cascade="all, delete-orphan")


class JiraWorklog(Base, TimestampMixin):
    __tablename__ = "jira_worklogs"
    __table_args__ = (UniqueConstraint("jira_worklog_id", name="uq_jira_worklog_jira_worklog_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jira_worklog_id: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_id: Mapped[int] = mapped_column(ForeignKey("jira_issues.id"), nullable=False, index=True)
    author_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    updated_at_jira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    issue: Mapped["JiraIssue"] = relationship(back_populates="worklogs")
    author_agent: Mapped["Agent | None"] = relationship(back_populates="worklogs")


class SyncState(Base, TimestampMixin):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ClientCompany(Base, TimestampMixin):
    __tablename__ = "client_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    informers: Mapped[list["CompanyInformer"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class CompanyInformer(Base, TimestampMixin):
    __tablename__ = "company_informers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("client_companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jira_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped["ClientCompany"] = relationship(back_populates="informers")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), default="Administrador", nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
