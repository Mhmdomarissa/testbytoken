"""Administrator UI and APIs for users, roles, permissions, and audit logs."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from webapp.models import AccessRole, AuditLog, ClientMachine, RolePermission, User, WorkerAgent, db
from webapp.rbac import (
    PLATFORM_MODULES,
    all_permissions_for_role,
    apply_role_mode,
    apply_role_permission_template,
    current_user,
    detect_role_mode,
    invalidate_user_sessions,
    is_administrator,
    permission_required,
    record_audit,
    role_mode_options,
    ROLE_MODES,
    user_has_any_view_permission,
    validate_password,
)
from webapp.worker_installer import worker_installer_for_platform
from webapp.worker_service import find_online_worker


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _active_roles() -> list[AccessRole]:
    return AccessRole.query.filter_by(is_active=True).order_by(AccessRole.name).all()


def _normalise_optional(value: str) -> str | None:
    value = (value or "").strip()
    return value or None


def _find_duplicate_user(
    username: str,
    email: str | None,
    employee_id: str | None,
    exclude_id: int | None = None,
) -> User | None:
    checks = [db.func.lower(User.username) == username.lower()]
    if email:
        checks.append(db.func.lower(User.email) == email.lower())
    if employee_id:
        checks.append(User.employee_id == employee_id)
    query = User.query.filter(or_(*checks))
    if exclude_id:
        query = query.filter(User.id != exclude_id)
    return query.first()


def _apply_user_fields(user: User, form, role: AccessRole) -> None:
    user.employee_name = form.get("employee_name", "").strip()
    user.employee_id = _normalise_optional(form.get("employee_id", ""))
    user.email = _normalise_optional(form.get("email", ""))
    user.mobile_number = form.get("mobile_number", "").strip()
    user.department = form.get("department", "").strip()
    user.designation = form.get("designation", "").strip()
    user.username = form.get("username", "").strip()
    user.role_id = role.id
    user.role = role.name
    user.is_active = form.get("is_active") == "on"
    user.is_deleted = False


@admin_bp.get("/users")
@permission_required("user_management", "view")
def users():
    roles = _active_roles()
    query = User.query
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "all").strip()
    selected_role_id = request.args.get("role_id", type=int)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                User.username.ilike(like),
                User.employee_name.ilike(like),
                User.email.ilike(like),
                User.employee_id.ilike(like),
                User.department.ilike(like),
            )
        )
    if status == "active":
        query = query.filter_by(is_active=True, is_deleted=False)
    elif status == "inactive":
        query = query.filter_by(is_active=False, is_deleted=False)
    elif status == "deleted":
        query = query.filter_by(is_deleted=True)
    else:
        query = query.filter_by(is_deleted=False)
    if selected_role_id:
        query = query.filter(User.role_id == selected_role_id)
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 100
    total = query.count()
    items = (
        query.order_by(User.employee_name, User.username)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return render_template(
        "admin/users.html",
        users=items,
        roles=roles,
        search=search,
        status=status,
        selected_role_id=selected_role_id,
        page=page,
        per_page=per_page,
        total=total,
        pages=max((total + per_page - 1) // per_page, 1),
    )


@admin_bp.post("/users")
@permission_required("user_management", "create")
def create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    employee_name = request.form.get("employee_name", "").strip()
    role = db.session.get(AccessRole, request.form.get("role_id", type=int))
    email = _normalise_optional(request.form.get("email", ""))
    employee_id = _normalise_optional(request.form.get("employee_id", ""))
    errors = validate_password(password, username)
    if not username or not employee_name:
        errors.append("Employee name and username are required.")
    if not role or not role.is_active:
        errors.append("Select an active role.")
    if _find_duplicate_user(username, email, employee_id):
        errors.append("Username, employee ID, or email already exists.")
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.users"))

    if not all_permissions_for_role(role):
        flash(
            f'Warning: role "{role.name}" has no permissions yet. The user may only see a "no access" page until permissions are set.',
            "error",
        )

    user = User(password_hash=generate_password_hash(password))
    _apply_user_fields(user, request.form, role)
    user.password_changed_at = datetime.utcnow()
    db.session.add(user)
    db.session.flush()
    record_audit(
        "USER_CREATED",
        "user_management",
        target=user,
        remarks=f"Created user {user.username} with role {role.name}",
        details={"role": role.name, "active": user.is_active},
    )
    record_audit(
        "ROLE_ASSIGNED",
        "role_management",
        target=user,
        remarks=f"Assigned {role.name} to {user.username}",
    )
    db.session.commit()
    flash(f'User "{user.username}" created.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.get("/users/<int:user_id>/edit")
@permission_required("user_management", "edit")
def edit_user_form(user_id: int):
    user = db.get_or_404(User, user_id)
    return render_template("admin/user_edit.html", user=user, roles=_active_roles())


@admin_bp.post("/users/<int:user_id>/edit")
@permission_required("user_management", "edit")
def edit_user(user_id: int):
    user = db.get_or_404(User, user_id)
    username = request.form.get("username", "").strip()
    employee_name = request.form.get("employee_name", "").strip()
    email = _normalise_optional(request.form.get("email", ""))
    employee_id = _normalise_optional(request.form.get("employee_id", ""))
    role = db.session.get(AccessRole, request.form.get("role_id", type=int))
    errors: list[str] = []
    if not username or not employee_name:
        errors.append("Employee name and username are required.")
    if not role or not role.is_active:
        errors.append("Select an active role.")
    if _find_duplicate_user(username, email, employee_id, exclude_id=user.id):
        errors.append("Username, employee ID, or email already exists.")
    actor = current_user()
    if actor and actor.id == user.id and request.form.get("is_active") != "on":
        errors.append("You cannot deactivate your own account.")
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.edit_user_form", user_id=user.id))

    before = {
        "username": user.username,
        "role": user.access_role.name if user.access_role else user.role,
        "active": user.is_active,
    }
    _apply_user_fields(user, request.form, role)
    invalidate_user_sessions(user)
    record_audit(
        "USER_UPDATED",
        "user_management",
        target=user,
        remarks=f"Updated user {user.username}",
        details={
            "before": before,
            "after": {"username": user.username, "role": role.name, "active": user.is_active},
        },
    )
    if before["role"] != role.name:
        record_audit(
            "ROLE_ASSIGNED",
            "role_management",
            target=user,
            remarks=f"Changed role from {before['role']} to {role.name}",
        )
    db.session.commit()
    if actor and actor.id == user.id:
        session["session_version"] = user.session_version
        session["username"] = user.username
        session["role"] = role.name
    flash(f'User "{user.username}" updated.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/toggle")
@permission_required("user_management", "edit")
def toggle_user(user_id: int):
    user = db.get_or_404(User, user_id)
    actor = current_user()
    if actor and actor.id == user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    invalidate_user_sessions(user)
    action = "USER_ACTIVATED" if user.is_active else "USER_DEACTIVATED"
    record_audit(action, "user_management", target=user, remarks=f"{action}: {user.username}")
    db.session.commit()
    flash(f'User "{user.username}" is now {"active" if user.is_active else "inactive"}.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/reset-password")
@permission_required("user_management", "edit")
def reset_user_password(user_id: int):
    user = db.get_or_404(User, user_id)
    password = request.form.get("password", "")
    errors = validate_password(password, user.username)
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("admin.edit_user_form", user_id=user.id))
    user.password_hash = generate_password_hash(password)
    user.password_changed_at = datetime.utcnow()
    user.failed_login_attempts = 0
    user.locked_until = None
    invalidate_user_sessions(user)
    record_audit(
        "PASSWORD_RESET",
        "user_management",
        target=user,
        remarks=f"Password reset for {user.username}",
    )
    db.session.commit()
    flash(f'Password reset for "{user.username}".', "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/delete")
@permission_required("user_management", "delete")
def delete_user(user_id: int):
    user = db.get_or_404(User, user_id)
    actor = current_user()
    if actor and actor.id == user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.users"))
    user.is_deleted = True
    user.is_active = False
    invalidate_user_sessions(user)
    record_audit(
        "USER_DELETED",
        "user_management",
        target=user,
        remarks=f"Soft deleted user {user.username}",
    )
    db.session.commit()
    flash(f'User "{user.username}" deleted (soft delete).', "success")
    return redirect(url_for("admin.users"))


@admin_bp.get("/users/export")
@permission_required("user_management", "export")
def export_users():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Employee Name",
            "Employee ID",
            "Email",
            "Mobile Number",
            "Department",
            "Designation",
            "Username",
            "Status",
            "Role",
        ]
    )
    for user in User.query.filter_by(is_deleted=False).order_by(User.username):
        writer.writerow(
            [
                user.employee_name,
                user.employee_id or "",
                user.email or "",
                user.mobile_number,
                user.department,
                user.designation,
                user.username,
                "Active" if user.is_active else "Inactive",
                user.access_role.name if user.access_role else user.role,
            ]
        )
    record_audit(
        "USERS_EXPORTED",
        "user_management",
        remarks="Exported users to CSV",
        commit=True,
    )
    data = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        data,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"users-{datetime.utcnow():%Y%m%d-%H%M%S}.csv",
    )


@admin_bp.post("/users/import")
@permission_required("user_management", "import")
def import_users():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a CSV file.", "error")
        return redirect(url_for("admin.users"))
    try:
        content = upload.stream.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        created = 0
        skipped: list[str] = []
        roles = {role.name.lower(): role for role in _active_roles()}
        for row_number, row in enumerate(reader, start=2):
            username = (row.get("Username") or row.get("username") or "").strip()
            password = row.get("Password") or row.get("password") or ""
            role_name = (row.get("Role") or row.get("role") or "Viewer").strip().lower()
            role = roles.get(role_name)
            employee_name = (
                row.get("Employee Name") or row.get("employee_name") or username
            ).strip()
            email = _normalise_optional(row.get("Email") or row.get("email") or "")
            employee_id = _normalise_optional(
                row.get("Employee ID") or row.get("employee_id") or ""
            )
            if (
                not username
                or not role
                or validate_password(password, username)
                or _find_duplicate_user(username, email, employee_id)
            ):
                skipped.append(str(row_number))
                continue
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                employee_name=employee_name,
                employee_id=employee_id,
                email=email,
                mobile_number=(row.get("Mobile Number") or row.get("mobile_number") or "").strip(),
                department=(row.get("Department") or row.get("department") or "").strip(),
                designation=(row.get("Designation") or row.get("designation") or "").strip(),
                role_id=role.id,
                role=role.name,
                is_active=(row.get("Status") or "Active").strip().lower() == "active",
                password_changed_at=datetime.utcnow(),
            )
            db.session.add(user)
            created += 1
        record_audit(
            "USERS_IMPORTED",
            "user_management",
            remarks=f"Imported {created} users; skipped {len(skipped)} rows",
            details={"skipped_rows": skipped},
        )
        db.session.commit()
        flash(f"Imported {created} user(s). Skipped {len(skipped)} row(s).", "success")
    except (UnicodeDecodeError, csv.Error) as exc:
        db.session.rollback()
        flash(f"Invalid CSV file: {exc}", "error")
    return redirect(url_for("admin.users"))


@admin_bp.get("/roles")
@permission_required("role_management", "view")
def roles():
    items = AccessRole.query.order_by(AccessRole.name).all()
    return render_template(
        "admin/roles.html",
        roles=items,
        modules=PLATFORM_MODULES,
        role_modes=role_mode_options(),
        ROLE_MODES=ROLE_MODES,
        detect_role_mode=detect_role_mode,
    )


@admin_bp.post("/roles")
@permission_required("role_management", "create")
def create_role():
    name = request.form.get("name", "").strip()
    if not name or AccessRole.query.filter(db.func.lower(AccessRole.name) == name.lower()).first():
        flash("Enter a unique role name.", "error")
        return redirect(url_for("admin.roles"))
    role = AccessRole(
        name=name,
        description=request.form.get("description", "").strip(),
        is_active=True,
        is_system=False,
    )
    db.session.add(role)
    db.session.flush()
    mode_key = (request.form.get("role_mode") or "Viewer").strip()
    if not apply_role_mode(role, mode_key):
        apply_role_permission_template(role, "Viewer")
    record_audit(
        "ROLE_CREATED",
        "role_management",
        remarks=f"Created role {role.name}",
    )
    db.session.commit()
    flash(
        f'Role "{role.name}" created in {ROLE_MODES.get(mode_key, {}).get("label", mode_key)} mode. Review permissions below.',
        "success",
    )
    return redirect(url_for("admin.edit_role_form", role_id=role.id))


@admin_bp.get("/roles/<int:role_id>")
@permission_required("role_management", "edit")
def edit_role_form(role_id: int):
    role = db.get_or_404(AccessRole, role_id)
    return render_template(
        "admin/role_edit.html",
        role=role,
        modules=PLATFORM_MODULES,
        selected=all_permissions_for_role(role),
        role_modes=role_mode_options(),
        ROLE_MODES=ROLE_MODES,
        detected_mode=detect_role_mode(role),
    )


@admin_bp.post("/roles/<int:role_id>/apply-mode")
@permission_required("role_management", "edit")
def apply_role_mode_view(role_id: int):
    role = db.get_or_404(AccessRole, role_id)
    if role.is_system:
        flash("System roles cannot change mode.", "error")
        return redirect(url_for("admin.edit_role_form", role_id=role.id))
    mode_key = (request.form.get("role_mode") or "TestUser").strip()
    if not apply_role_mode(role, mode_key):
        flash("Unknown role mode.", "error")
        return redirect(url_for("admin.edit_role_form", role_id=role.id))
    for user in role.users:
        invalidate_user_sessions(user)
    record_audit(
        "PERMISSION_CHANGED",
        "role_management",
        remarks=f"Applied {mode_key} mode to role {role.name}",
        details={"role_id": role.id, "mode": mode_key},
    )
    db.session.commit()
    label = ROLE_MODES.get(mode_key, {}).get("label", mode_key)
    flash(f'Role "{role.name}" updated to {label} mode.', "success")
    return redirect(url_for("admin.edit_role_form", role_id=role.id))


@admin_bp.post("/roles/<int:role_id>")
@permission_required("role_management", "edit")
def edit_role(role_id: int):
    role = db.get_or_404(AccessRole, role_id)
    old_name = role.name
    name = request.form.get("name", "").strip()
    duplicate = AccessRole.query.filter(
        db.func.lower(AccessRole.name) == name.lower(), AccessRole.id != role.id
    ).first()
    if not name or duplicate:
        flash("Enter a unique role name.", "error")
        return redirect(url_for("admin.edit_role_form", role_id=role.id))
    if role.is_system and name != role.name:
        flash("The system Administrator role cannot be renamed.", "error")
        return redirect(url_for("admin.edit_role_form", role_id=role.id))

    role.name = name
    role.description = request.form.get("description", "").strip()
    role.is_active = True if role.is_system else request.form.get("is_active") == "on"
    RolePermission.query.filter_by(role_id=role.id).delete(synchronize_session=False)
    for module, definition in PLATFORM_MODULES.items():
        for action in definition["actions"]:
            if request.form.get(f"perm__{module}__{action}") == "on":
                db.session.add(
                    RolePermission(
                        role_id=role.id,
                        module=module,
                        action=action,
                        allowed=True,
                    )
                )
    if role.is_system:
        # Administrator remains unrestricted even if a checkbox was omitted.
        for module, definition in PLATFORM_MODULES.items():
            for action in definition["actions"]:
                if not RolePermission.query.filter_by(
                    role_id=role.id, module=module, action=action
                ).first():
                    db.session.add(
                        RolePermission(
                            role_id=role.id,
                            module=module,
                            action=action,
                            allowed=True,
                        )
                    )
    actor = current_user()
    for user in role.users:
        user.role = role.name
        invalidate_user_sessions(user)
    record_audit(
        "PERMISSION_CHANGED",
        "role_management",
        remarks=f"Updated role {old_name}",
        details={"role_id": role.id, "new_name": role.name},
    )
    db.session.commit()
    if actor and actor.role_id == role.id:
        session["session_version"] = actor.session_version
        session["role"] = role.name
    flash(f'Role "{role.name}" and permissions updated.', "success")
    return redirect(url_for("admin.roles"))


@admin_bp.post("/roles/<int:role_id>/clone")
@permission_required("role_management", "create")
def clone_role(role_id: int):
    source = db.get_or_404(AccessRole, role_id)
    base = f"{source.name} Copy"
    name = base
    suffix = 2
    while AccessRole.query.filter(db.func.lower(AccessRole.name) == name.lower()).first():
        name = f"{base} {suffix}"
        suffix += 1
    clone = AccessRole(
        name=name,
        description=f"Cloned from {source.name}",
        is_active=True,
        is_system=False,
    )
    db.session.add(clone)
    db.session.flush()
    for permission in source.permissions:
        db.session.add(
            RolePermission(
                role_id=clone.id,
                module=permission.module,
                action=permission.action,
                allowed=permission.allowed,
            )
        )
    record_audit(
        "ROLE_CLONED",
        "role_management",
        remarks=f"Cloned {source.name} to {clone.name}",
    )
    db.session.commit()
    flash(f'Role cloned as "{clone.name}".', "success")
    return redirect(url_for("admin.edit_role_form", role_id=clone.id))


@admin_bp.post("/roles/<int:role_id>/delete")
@permission_required("role_management", "delete")
def delete_role(role_id: int):
    role = db.get_or_404(AccessRole, role_id)
    if role.is_system:
        flash("The system Administrator role cannot be deleted.", "error")
    elif role.users:
        flash("Reassign users before deleting this role.", "error")
    else:
        name = role.name
        db.session.delete(role)
        record_audit("ROLE_DELETED", "role_management", remarks=f"Deleted role {name}")
        db.session.commit()
        flash(f'Role "{name}" deleted.', "success")
    return redirect(url_for("admin.roles"))


@admin_bp.get("/audit-logs")
@permission_required("audit_logs", "view")
def audit_logs():
    query = AuditLog.query
    action = request.args.get("action", "").strip()
    module = request.args.get("module", "").strip()
    if action:
        query = query.filter(AuditLog.action == action)
    if module:
        query = query.filter(AuditLog.module == module)
    logs = query.order_by(AuditLog.created_at.desc()).limit(1000).all()
    actions = [
        item[0] for item in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action)
    ]
    modules = [
        item[0] for item in db.session.query(AuditLog.module).distinct().order_by(AuditLog.module)
    ]
    return render_template(
        "admin/audit_logs.html",
        logs=logs,
        actions=actions,
        modules=modules,
        selected_action=action,
        selected_module=module,
    )


@admin_bp.get("/audit-logs/export")
@permission_required("audit_logs", "export")
def export_audit_logs():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date & Time", "User", "Action", "Module", "IP Address", "Remarks"])
    for log in AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10000):
        writer.writerow(
            [
                log.created_at.isoformat(sep=" ", timespec="seconds"),
                log.actor.username if log.actor else "System/Unknown",
                log.action,
                log.module,
                log.ip_address,
                log.remarks,
            ]
        )
    record_audit(
        "AUDIT_EXPORTED",
        "audit_logs",
        remarks="Exported audit logs to CSV",
        commit=True,
    )
    data = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(
        data,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"audit-logs-{datetime.utcnow():%Y%m%d-%H%M%S}.csv",
    )


@admin_bp.get("/machines")
@permission_required("user_management", "view")
def machines():
    """Simple admin view: register client IP/user and download connector."""
    rows = (
        ClientMachine.query.order_by(ClientMachine.updated_at.desc(), ClientMachine.id.desc()).all()
    )
    users = (
        User.query.filter_by(is_deleted=False, is_active=True)
        .order_by(User.username)
        .all()
    )
    status_by_user: dict[int, dict] = {}
    for user in users:
        worker = find_online_worker(user.id)
        if worker:
            status_by_user[user.id] = {
                "online": True,
                "machine_name": worker.machine_name,
                "last_seen_at": worker.last_seen_at,
            }
        else:
            latest = (
                WorkerAgent.query.filter_by(user_id=user.id)
                .order_by(WorkerAgent.last_seen_at.desc())
                .first()
            )
            status_by_user[user.id] = {
                "online": False,
                "machine_name": latest.machine_name if latest else "",
                "last_seen_at": latest.last_seen_at if latest else None,
            }
    return render_template(
        "admin/machines.html",
        machines=rows,
        users=users,
        status_by_user=status_by_user,
    )


@admin_bp.post("/machines")
@permission_required("user_management", "create")
def create_machine():
    user_id = request.form.get("user_id", type=int)
    ip_address = (request.form.get("ip_address") or "").strip()
    label = (request.form.get("label") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    user = db.session.get(User, user_id) if user_id else None
    if not user or user.is_deleted:
        flash("Select a valid user.", "error")
        return redirect(url_for("admin.machines"))
    if not ip_address:
        flash("Client IP is required.", "error")
        return redirect(url_for("admin.machines"))

    existing = ClientMachine.query.filter_by(user_id=user.id, ip_address=ip_address).first()
    if existing:
        existing.label = label or existing.label
        existing.notes = notes or existing.notes
        flash(f"Updated machine for {user.username} ({ip_address}).", "success")
    else:
        db.session.add(
            ClientMachine(
                user_id=user.id,
                ip_address=ip_address,
                label=label or f"{user.username} PC",
                notes=notes,
            )
        )
        flash(f"Added {user.username} @ {ip_address}. Download connector and run it on that PC once.", "success")
    record_audit(
        "CLIENT_MACHINE_SAVED",
        "user_management",
        target=user,
        remarks=f"IP {ip_address} label={label}",
    )
    db.session.commit()
    return redirect(url_for("admin.machines"))


@admin_bp.post("/machines/<int:machine_id>/delete")
@permission_required("user_management", "delete")
def delete_machine(machine_id: int):
    machine = db.get_or_404(ClientMachine, machine_id)
    record_audit(
        "CLIENT_MACHINE_DELETED",
        "user_management",
        target=machine.user,
        remarks=f"Removed IP {machine.ip_address}",
    )
    db.session.delete(machine)
    db.session.commit()
    flash("Client machine removed.", "success")
    return redirect(url_for("admin.machines"))


@admin_bp.get("/machines/<int:machine_id>/connector")
@permission_required("user_management", "view")
def download_machine_connector(machine_id: int):
    machine = db.get_or_404(ClientMachine, machine_id)
    user = machine.user
    if not user or user.is_deleted:
        flash("User missing for this machine.", "error")
        return redirect(url_for("admin.machines"))
    server_url = (request.url_root or "").rstrip("/")
    platform = request.args.get("platform", "win")
    filename, content = worker_installer_for_platform(
        server_url=server_url, username=user.username, platform=platform
    )
    record_audit(
        "CLIENT_CONNECTOR_DOWNLOADED",
        "user_management",
        target=user,
        remarks=f"Connector for IP {machine.ip_address}",
        commit=True,
    )
    return Response(
        content,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
