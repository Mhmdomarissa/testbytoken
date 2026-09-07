"""Relational model for UTS projects, RBAC, repositories, and executions."""

from __future__ import annotations

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint


db = SQLAlchemy()


def utcnow() -> datetime:
    return datetime.utcnow()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    employee_name = db.Column(db.String(160), default="", nullable=False)
    employee_id = db.Column(db.String(80), unique=True, index=True)
    email = db.Column(db.String(255), unique=True, index=True)
    mobile_number = db.Column(db.String(40), default="", nullable=False)
    department = db.Column(db.String(120), default="", nullable=False)
    designation = db.Column(db.String(120), default="", nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("access_role.id"), index=True)
    # Legacy display field kept for existing installations and integrations.
    role = db.Column(db.String(40), default="Tester", nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)
    session_version = db.Column(db.Integer, default=1, nullable=False)
    last_login_at = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    access_role = db.relationship("AccessRole", back_populates="users")


class AccessRole(db.Model):
    __table_args__ = (UniqueConstraint("name", name="uq_access_role_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, index=True)
    description = db.Column(db.Text, default="")
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    users = db.relationship("User", back_populates="access_role")
    permissions = db.relationship(
        "RolePermission",
        cascade="all, delete-orphan",
        back_populates="access_role",
        lazy="selectin",
    )


class RolePermission(db.Model):
    __table_args__ = (
        UniqueConstraint("role_id", "module", "action", name="uq_role_module_action"),
    )

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(
        db.Integer,
        db.ForeignKey("access_role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module = db.Column(db.String(80), nullable=False, index=True)
    action = db.Column(db.String(40), nullable=False)
    allowed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    access_role = db.relationship("AccessRole", back_populates="permissions")


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    module = db.Column(db.String(80), nullable=False, index=True)
    ip_address = db.Column(db.String(64), default="")
    remarks = db.Column(db.Text, default="")
    details = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    actor = db.relationship("User", foreign_keys=[actor_user_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    application_url = db.Column(db.Text, nullable=False)
    app_username = db.Column(db.String(255), default="")
    app_password = db.Column(db.String(255), default="")
    app_role = db.Column(db.String(120), default="")
    browser = db.Column(db.String(30), default="chrome", nullable=False)
    status = db.Column(db.String(30), default="NEW", nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    modules = db.relationship("Module", cascade="all, delete-orphan", backref="project")
    scans = db.relationship("ScanHistory", cascade="all, delete-orphan", backref="project")
    executions = db.relationship("Execution", cascade="all, delete-orphan", backref="project")


class ScanHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    scan_type = db.Column(db.String(30), default="MODULES", nullable=False)
    status = db.Column(db.String(30), default="QUEUED", nullable=False)
    message = db.Column(db.Text, default="")
    module_count = db.Column(db.Integer, default=0)
    page_count = db.Column(db.Integer, default=0)
    object_count = db.Column(db.Integer, default=0)
    artifact_path = db.Column(db.Text, default="")
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class Module(db.Model):
    __table_args__ = (UniqueConstraint("project_id", "external_key", name="uq_project_module"),)

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    external_key = db.Column(db.String(160), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    selected = db.Column(db.Boolean, default=False, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    pages = db.relationship("Page", cascade="all, delete-orphan", backref="module")
    flows = db.relationship("BusinessFlow", cascade="all, delete-orphan", backref="module")


class Page(db.Model):
    __table_args__ = (UniqueConstraint("module_id", "path", name="uq_module_page_path"),)

    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    path = db.Column(db.String(500), nullable=False)
    url = db.Column(db.Text, default="")
    page_type = db.Column(db.String(80), default="unknown")
    parent_path = db.Column(db.String(500), default="")
    screenshot_path = db.Column(db.Text, default="")
    summary = db.Column(db.Text, default="")
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    objects = db.relationship("UIObject", cascade="all, delete-orphan", backref="page")


class UIObject(db.Model):
    __table_args__ = (
        UniqueConstraint("project_id", "repository_key", name="uq_project_repository_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    page_id = db.Column(db.Integer, db.ForeignKey("page.id"), index=True)
    repository_key = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(80), default="element")
    locator_by = db.Column(db.String(30), default="")
    locator_value = db.Column(db.Text, default="")
    alternate_locators = db.Column(db.JSON)
    stable_score = db.Column(db.Integer, default=0)
    fingerprint = db.Column(db.String(64), default="", index=True)
    attributes = db.Column(db.JSON)
    screenshot_path = db.Column(db.Text, default="")
    first_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    change_count = db.Column(db.Integer, default=0, nullable=False)


class BusinessFlow(db.Model):
    __table_args__ = (UniqueConstraint("module_id", "external_key", name="uq_module_flow"),)

    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), nullable=False, index=True)
    external_key = db.Column(db.String(160), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    navigation_path = db.Column(db.Text, default="")
    parent_flow_id = db.Column(db.Integer, db.ForeignKey("business_flow.id"))
    actions = db.Column(db.JSON)
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    test_cases = db.relationship("TestCase", cascade="all, delete-orphan", backref="flow")


class TestCase(db.Model):
    __table_args__ = (UniqueConstraint("project_id", "external_key", name="uq_project_testcase"),)

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), index=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("business_flow.id"), index=True)
    external_key = db.Column(db.String(160), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    test_type = db.Column(db.String(40), default="automation")
    manual_steps = db.Column(db.JSON)
    automation_steps = db.Column(db.JSON)
    expected_result = db.Column(db.Text, default="")
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    module = db.relationship("Module", backref=db.backref("test_cases", lazy="dynamic"))


class Execution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    module_names = db.Column(db.JSON)
    test_case_ids = db.Column(db.JSON)
    status = db.Column(db.String(30), default="QUEUED", nullable=False)
    passed = db.Column(db.Integer, default=0)
    failed = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    current_step = db.Column(db.Text, default="")
    report_path = db.Column(db.Text, default="")
    message = db.Column(db.Text, default="")
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class ExecutionStep(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("execution.id"), nullable=False, index=True)
    test_case_key = db.Column(db.String(160), default="")
    sequence = db.Column(db.Integer, nullable=False)
    name = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="PENDING")
    message = db.Column(db.Text, default="")
    screenshot_path = db.Column(db.Text, default="")
    duration_ms = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class WorkerAgent(db.Model):
    """A user's machine that can run Selenium locally (Option B)."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(255), nullable=False, unique=True, index=True)
    machine_name = db.Column(db.String(160), default="", nullable=False)
    platform = db.Column(db.String(40), default="", nullable=False)
    browser = db.Column(db.String(30), default="chrome", nullable=False)
    status = db.Column(db.String(30), default="OFFLINE", nullable=False, index=True)
    last_seen_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", backref="workers")
    jobs = db.relationship("WorkerJob", back_populates="worker")


class ClientMachine(db.Model):
    """Admin-registered client PC (IP label + user). Connector must run once on that PC."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    ip_address = db.Column(db.String(80), default="", nullable=False)
    label = db.Column(db.String(160), default="", nullable=False)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user = db.relationship("User", backref="client_machines")


class WorkerJob(db.Model):
    """Automation job queued for a specific user's worker machine."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("worker_agent.id"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    history_id = db.Column(db.Integer, db.ForeignKey("scan_history.id"), index=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("execution.id"), index=True)
    job_type = db.Column(db.String(40), nullable=False)  # MODULES | FLOW | EXECUTION | PIPELINE
    payload = db.Column(db.JSON)
    status = db.Column(db.String(30), default="QUEUED", nullable=False, index=True)
    message = db.Column(db.Text, default="")
    stop_requested = db.Column(db.Boolean, default=False, nullable=False)
    result = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    claimed_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    worker = db.relationship("WorkerAgent", back_populates="jobs")
    user = db.relationship("User")
    project = db.relationship("Project")
