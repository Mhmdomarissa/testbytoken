"""Role-based access control, password policy, and audit helpers."""

from __future__ import annotations

import re
import os
from datetime import datetime, timedelta
from functools import wraps
from typing import Any

from flask import abort, g, jsonify, redirect, request, session, url_for

from webapp.models import AccessRole, AuditLog, Project, RolePermission, User, db


PERMISSION_ACTIONS = ("view", "create", "edit", "delete", "approve", "export", "import", "print", "execute")

PLATFORM_MODULES: dict[str, dict[str, Any]] = {
    "dashboard": {"label": "Dashboard", "actions": ("view",)},
    "projects": {
        "label": "Automation Projects",
        "actions": ("view", "create", "edit", "delete", "execute", "export", "import"),
    },
    "api_farm": {
        "label": "API Test",
        "actions": ("view", "create", "edit", "delete", "execute", "export", "import"),
    },
    "customer_management": {
        "label": "Customer Management",
        "actions": ("view", "create", "edit", "delete", "approve", "export", "import", "print"),
    },
    "vendor_management": {
        "label": "Vendor Management",
        "actions": ("view", "create", "edit", "delete", "approve", "export", "import", "print"),
    },
    "inventory": {
        "label": "Inventory",
        "actions": ("view", "create", "edit", "delete", "approve", "export", "import", "print"),
    },
    "purchase": {
        "label": "Purchase",
        "actions": ("view", "create", "edit", "delete", "approve", "export", "import", "print"),
    },
    "sales": {
        "label": "Sales",
        "actions": ("view", "create", "edit", "delete", "approve", "export", "import", "print"),
    },
    "finance": {
        "label": "Finance",
        "actions": ("view", "create", "edit", "delete", "approve", "export", "import", "print"),
    },
    "user_management": {
        "label": "User Management",
        "actions": ("view", "create", "edit", "delete", "export", "import"),
    },
    "role_management": {
        "label": "Role Management",
        "actions": ("view", "create", "edit", "delete"),
    },
    "audit_logs": {"label": "Audit Logs", "actions": ("view", "export", "print")},
    "settings": {"label": "Settings", "actions": ("view", "edit")},
    "reports": {"label": "Reports", "actions": ("view", "export", "print")},
}

ADMIN_ROLE_NAMES = {"admin", "administrator"}

DEFAULT_ROLE_PERMISSIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "Administrator": {
        module: tuple(definition["actions"]) for module, definition in PLATFORM_MODULES.items()
    },
    "Manager": {
        "dashboard": ("view",),
        "projects": ("view", "create", "edit", "execute", "export", "import"),
        "api_farm": ("view", "create", "edit", "execute", "export", "import"),
        "reports": ("view", "export", "print"),
    },
    "Supervisor": {
        "dashboard": ("view",),
        "projects": ("view", "edit", "execute", "export"),
        "api_farm": ("view", "create", "edit", "execute", "export"),
        "reports": ("view", "export"),
    },
    "Executive": {
        "dashboard": ("view",),
        "projects": ("view", "execute"),
        "api_farm": ("view", "execute"),
        "reports": ("view",),
    },
    "Viewer": {
        "dashboard": ("view",),
        "projects": ("view",),
        "api_farm": ("view",),
        "reports": ("view",),
    },
    "TestUser": {
        "dashboard": ("view",),
        "projects": ("view", "execute"),
        "api_farm": ("view", "execute"),
        "reports": ("view",),
    },
}

TESTER_ROLE_NAMES = {"testuser", "tester"}

ROLE_MODES: dict[str, dict[str, str]] = {
    "TestUser": {
        "label": "Tester",
        "description": "Scan & run only — no project create/edit/delete",
    },
    "Executive": {
        "label": "Standard user",
        "description": "View and execute projects/API tests",
    },
    "Viewer": {
        "label": "Viewer",
        "description": "Read-only access",
    },
    "Supervisor": {
        "label": "Supervisor",
        "description": "View, edit, and execute automation",
    },
    "Manager": {
        "label": "Manager",
        "description": "Full project and API test management",
    },
}


def role_mode_options() -> list[dict[str, str]]:
    return [
        {"key": key, **meta}
        for key, meta in ROLE_MODES.items()
    ]


def apply_role_mode(role: AccessRole, mode_key: str) -> bool:
    permissions = DEFAULT_ROLE_PERMISSIONS.get(mode_key)
    if not permissions:
        return False
    set_role_permissions(role, permissions)
    meta = ROLE_MODES.get(mode_key, {})
    if meta.get("description") and not (role.description or "").strip():
        role.description = meta["description"]
    return True


def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_role_name(value: str) -> str:
    value = (value or "").strip()
    if value.lower() == "admin":
        return "Administrator"
    if value.lower() in {"tester", "test user", "testuser"}:
        return "TestUser"
    if value.lower() in {"standard user"}:
        return "Executive"
    if value.lower() in {"guest", "guest user", "read-only user"}:
        return "Viewer"
    return value


def current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, int(user_id))
    if not user or not user.is_active or user.is_deleted:
        return None
    if int(session.get("session_version", 0)) != int(user.session_version or 1):
        return None
    return user


def is_administrator(user: User | None) -> bool:
    if not user:
        return False
    name = user.access_role.name if user.access_role else user.role
    return (name or "").strip().lower() in ADMIN_ROLE_NAMES


def projects_visible_to(user: User | None):
    """Admins see every project; other users only see projects they created."""
    query = Project.query
    if not user:
        return query.filter(db.false())
    if is_administrator(user):
        return query
    return query.filter(Project.created_by == user.id)


def user_can_access_project(user: User | None, project: Project | None) -> bool:
    if not user or not project:
        return False
    if is_administrator(user):
        return True
    return project.created_by == user.id


def require_project_access(user: User | None, project: Project) -> None:
    if not user_can_access_project(user, project):
        abort(403)


def has_permission(user: User | None, module: str, action: str = "view") -> bool:
    """Resolve every permission from the database so changes apply immediately."""
    if not user or not user.is_active or user.is_deleted:
        return False
    if is_administrator(user):
        return True
    if not user.access_role or not user.access_role.is_active:
        return False
    cache_key = (user.id, user.session_version, user.access_role.id)
    if getattr(g, "_rbac_cache_key", None) != cache_key:
        g._rbac_cache_key = cache_key
        g._rbac_permissions = {
            (permission.module, permission.action)
            for permission in user.access_role.permissions
            if permission.allowed
        }
    return (module, action) in g._rbac_permissions


def wants_json_response() -> bool:
    return (
        request.path.startswith("/api/")
        or request.path.startswith("/api-farm/") and request.is_json
        or request.accept_mimetypes.best == "application/json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def permission_required(module: str, action: str = "view"):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if wants_json_response():
                    return jsonify(error="Authentication required"), 401
                session.clear()
                return redirect(url_for("web.login", next=request.path))
            if not has_permission(user, module, action):
                record_audit(
                    "ACCESS_DENIED",
                    module,
                    actor=user,
                    remarks=f"Denied {action} on {request.method} {request.path}",
                    commit=True,
                )
                if wants_json_response():
                    return jsonify(error="Access Denied", module=module, action=action), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def validate_password(password: str, username: str = "") -> list[str]:
    """Validate passwords.

    Simple deploy mode (UTS_SIMPLE_PASSWORDS=true) allows short passwords like
    admin/admin for direct package use on LAN/dev servers.
    """
    errors: list[str] = []
    simple = (os.getenv("UTS_SIMPLE_PASSWORDS") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not password:
        errors.append("Password is required.")
        return errors
    if simple:
        if len(password) < 4:
            errors.append("Password must be at least 4 characters.")
        return errors
    if len(password) < 10:
        errors.append("Password must be at least 10 characters.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain an uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain a lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain a number.")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("Password must contain a special character.")
    if username and username.lower() in password.lower():
        errors.append("Password must not contain the username.")
    return errors


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",", 1)[0].strip() if forwarded else request.remote_addr or "")[:64]


def record_audit(
    action: str,
    module: str,
    *,
    actor: User | None = None,
    target: User | None = None,
    remarks: str = "",
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> AuditLog:
    if actor is None:
        actor = current_user()
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        target_user_id=target.id if target else None,
        action=action[:80],
        module=module[:80],
        ip_address=client_ip(),
        remarks=remarks,
        details=details or {},
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def set_role_permissions(role: AccessRole, permissions: dict[str, tuple[str, ...]]) -> None:
    """Replace a role's allowed permissions with an exact template."""
    desired = {
        (module, action)
        for module, actions in permissions.items()
        for action in actions
    }
    for permission in RolePermission.query.filter_by(role_id=role.id).all():
        key = (permission.module, permission.action)
        if key in desired:
            permission.allowed = True
        else:
            db.session.delete(permission)
    for module, actions in permissions.items():
        for action in actions:
            exists = RolePermission.query.filter_by(
                role_id=role.id, module=module, action=action
            ).first()
            if not exists:
                db.session.add(
                    RolePermission(
                        role_id=role.id,
                        module=module,
                        action=action,
                        allowed=True,
                    )
                )


def sync_builtin_role_permissions() -> None:
    """Keep built-in roles aligned with the permission templates in code."""
    for role_name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        role = AccessRole.query.filter(
            db.func.lower(AccessRole.name) == role_name.lower()
        ).first()
        if not role:
            continue
        if role_name == "Administrator":
            for module, actions in permissions.items():
                for action in actions:
                    exists = RolePermission.query.filter_by(
                        role_id=role.id, module=module, action=action
                    ).first()
                    if not exists:
                        db.session.add(
                            RolePermission(
                                role_id=role.id,
                                module=module,
                                action=action,
                                allowed=True,
                            )
                        )
                    elif not exists.allowed:
                        exists.allowed = True
            continue
        set_role_permissions(role, permissions)
        meta = ROLE_MODES.get(role_name)
        if meta and meta.get("description"):
            role.description = meta["description"]


def detect_role_mode(role: AccessRole) -> str | None:
    current = all_permissions_for_role(role)
    for mode_key, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        desired = {
            (module, action)
            for module, actions in permissions.items()
            for action in actions
        }
        if current == desired:
            return mode_key
    return None


def sync_tester_role_permissions() -> None:
    """Backward-compatible alias for tester role sync."""
    sync_builtin_role_permissions()


def seed_default_roles() -> None:
    """Create standard roles and migrate existing users without deleting data."""
    roles: dict[str, AccessRole] = {}
    for role_name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        role = AccessRole.query.filter(db.func.lower(AccessRole.name) == role_name.lower()).first()
        if not role:
            role = AccessRole(
                name=role_name,
                description=f"Built-in {role_name} role",
                is_system=role_name == "Administrator",
                is_active=True,
            )
            db.session.add(role)
            db.session.flush()
        elif role_name == "Administrator":
            role.is_system = True
            role.is_active = True
        elif role_name == "TestUser":
            role.description = ROLE_MODES["TestUser"]["description"]
        roles[role_name] = role

        for module, actions in permissions.items():
            for action in actions:
                permission = RolePermission.query.filter_by(
                    role_id=role.id, module=module, action=action
                ).first()
                if not permission:
                    db.session.add(
                        RolePermission(
                            role_id=role.id,
                            module=module,
                            action=action,
                            allowed=True,
                        )
                    )

    db.session.flush()
    configured_admin = os.getenv("UTS_ADMIN_USERNAME", "admin").strip().lower()
    for user in User.query.all():
        if user.username.strip().lower() == configured_admin:
            role_name = "Administrator"
        elif user.role_id:
            continue
        else:
            role_name = normalize_role_name(user.role)
        role = roles.get(role_name) or roles["Executive"]
        user.role_id = role.id
        user.role = role.name
        user.employee_name = user.employee_name or user.username
        user.session_version = user.session_version or 1
    repair_roles_without_permissions()
    sync_builtin_role_permissions()
    db.session.commit()


def enforce_session_timeout(timeout_minutes: int) -> bool:
    """Return False and clear the session when idle timeout or user state invalidates it."""
    if not session.get("user_id"):
        return True
    user = current_user()
    if not user:
        session.clear()
        return False
    last_activity = session.get("last_activity")
    now = utcnow()
    if last_activity:
        try:
            previous = datetime.fromisoformat(last_activity)
            if now - previous > timedelta(minutes=timeout_minutes):
                record_audit(
                    "SESSION_TIMEOUT",
                    "authentication",
                    actor=user,
                    remarks="Session expired due to inactivity",
                    commit=True,
                )
                session.clear()
                return False
        except ValueError:
            pass
    session["last_activity"] = now.isoformat()
    session.permanent = True
    return True


def invalidate_user_sessions(user: User) -> None:
    user.session_version = int(user.session_version or 1) + 1


def all_permissions_for_role(role: AccessRole) -> set[tuple[str, str]]:
    return {
        (permission.module, permission.action)
        for permission in role.permissions
        if permission.allowed
    }


def apply_role_permission_template(role: AccessRole, template_name: str = "Viewer") -> int:
    """Copy a built-in permission template onto a role. Returns rows added."""
    permissions = DEFAULT_ROLE_PERMISSIONS.get(template_name, {})
    added = 0
    for module, actions in permissions.items():
        for action in actions:
            exists = RolePermission.query.filter_by(
                role_id=role.id, module=module, action=action
            ).first()
            if exists:
                if not exists.allowed:
                    exists.allowed = True
                    added += 1
                continue
            db.session.add(
                RolePermission(
                    role_id=role.id,
                    module=module,
                    action=action,
                    allowed=True,
                )
            )
            added += 1
    return added


def user_has_any_view_permission(user: User | None) -> bool:
    if not user:
        return False
    return any(
        has_permission(user, module, "view")
        for module in ("projects", "api_farm", "user_management", "role_management", "audit_logs")
    )


def repair_roles_without_permissions() -> int:
    """Give Viewer access to custom roles that were saved with zero permissions."""
    repaired = 0
    for role in AccessRole.query.filter_by(is_active=True).all():
        if role.is_system and (role.name or "").strip().lower() in ADMIN_ROLE_NAMES:
            continue
        allowed = RolePermission.query.filter_by(role_id=role.id, allowed=True).count()
        if allowed == 0:
            repaired += apply_role_permission_template(role, "Viewer")
    return repaired
