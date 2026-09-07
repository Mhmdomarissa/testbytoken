"""UTS web control plane."""

from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from webapp.models import AccessRole, User, db


ROOT = Path(__file__).resolve().parent.parent


def create_app(test_config: dict | None = None) -> Flask:
    database_url = os.getenv("DATABASE_URL", "sqlite:///web-data/uts_platform.db")
    if database_url.startswith("sqlite:///web-data/"):
        database_name = database_url.removeprefix("sqlite:///web-data/")
        database_url = f"sqlite:///{(ROOT / 'web-data' / database_name).as_posix()}"

    app = Flask(
        __name__,
        template_folder=str(ROOT / "webapp" / "templates"),
        static_folder=str(ROOT / "webapp" / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.getenv("UTS_SECRET_KEY", "change-this-before-production"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        UTS_ROOT=str(ROOT),
        PERMANENT_SESSION_LIFETIME=timedelta(
            minutes=int(os.getenv("UTS_SESSION_TIMEOUT_MINUTES", "30"))
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("UTS_SECURE_COOKIES", "false").lower() == "true",
    )
    if test_config:
        app.config.update(test_config)

    (ROOT / "web-data").mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from webapp.routes import bp
    from webapp.admin_routes import admin_bp
    from webapp.worker_routes import worker_bp

    app.register_blueprint(bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(worker_bp)

    _register_security_hooks(app)

    with app.app_context():
        db.create_all()
        _ensure_project_columns()
        _ensure_admin_user()
        from webapp.rbac import seed_default_roles

        seed_default_roles()

    return app


def _ensure_project_columns() -> None:
    """Add new columns to existing SQLite DBs without wiping data."""
    from sqlalchemy import text

    # project.app_role
    try:
        rows = db.session.execute(text("PRAGMA table_info(project)")).fetchall()
        existing = {row[1] for row in rows}
        if "app_role" not in existing:
            db.session.execute(text("ALTER TABLE project ADD COLUMN app_role VARCHAR(120) DEFAULT ''"))
            db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()

    _ensure_user_columns()


def _ensure_user_columns() -> None:
    """Add RBAC/user-management fields to an existing database in place."""
    from sqlalchemy import inspect, text

    try:
        existing = {column["name"] for column in inspect(db.engine).get_columns("user")}
    except Exception:  # noqa: BLE001
        return

    columns = {
        "employee_name": "VARCHAR(160) DEFAULT '' NOT NULL",
        "employee_id": "VARCHAR(80)",
        "email": "VARCHAR(255)",
        "mobile_number": "VARCHAR(40) DEFAULT '' NOT NULL",
        "department": "VARCHAR(120) DEFAULT '' NOT NULL",
        "designation": "VARCHAR(120) DEFAULT '' NOT NULL",
        "role_id": "INTEGER",
        "is_deleted": "BOOLEAN DEFAULT 0 NOT NULL",
        "failed_login_attempts": "INTEGER DEFAULT 0 NOT NULL",
        "locked_until": "DATETIME",
        "session_version": "INTEGER DEFAULT 1 NOT NULL",
        "last_login_at": "DATETIME",
        "password_changed_at": "DATETIME",
        "updated_at": "DATETIME",
    }
    try:
        for name, definition in columns.items():
            if name not in existing:
                db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {name} {definition}'))
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()

    # user.role
    try:
        rows = db.session.execute(text("PRAGMA table_info(user)")).fetchall()
        existing = {row[1] for row in rows}
        if "role" not in existing:
            db.session.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(40) DEFAULT 'Tester'"))
            db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()


def _ensure_admin_user() -> None:
    """Create or reset the bootstrap admin from .env so login always works."""
    from werkzeug.security import check_password_hash

    username = (os.getenv("UTS_ADMIN_USERNAME") or "admin").strip() or "admin"
    password = os.getenv("UTS_ADMIN_PASSWORD") or "admin"
    sync_password = (os.getenv("UTS_SYNC_ADMIN_PASSWORD") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    user = User.query.filter(db.func.lower(User.username) == username.lower()).first()
    if user is None:
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role="Admin",
            employee_name=username,
            is_active=True,
            is_deleted=False,
        )
        db.session.add(user)
        db.session.commit()
        return

    changed = False
    if not user.is_active or user.is_deleted:
        user.is_active = True
        user.is_deleted = False
        changed = True
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        changed = True
    if sync_password and not check_password_hash(user.password_hash, password):
        user.password_hash = generate_password_hash(password)
        user.session_version = int(user.session_version or 1) + 1
        changed = True
    if not user.employee_name:
        user.employee_name = username
        changed = True
    if not user.role:
        user.role = "Admin"
        changed = True
    if changed:
        db.session.commit()


def _register_security_hooks(app: Flask) -> None:
    from webapp.rbac import (
        PLATFORM_MODULES,
        current_user,
        enforce_session_timeout,
        has_permission,
        is_administrator,
    )

    @app.before_request
    def security_before_request():
        # Worker agents authenticate with Bearer tokens — skip cookie CSRF/session.
        if request.path.startswith("/api/worker/"):
            return None

        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf_token", "")
            if not supplied or not secrets.compare_digest(str(supplied), str(expected)):
                abort(400, description="Invalid or missing CSRF token.")

        if not enforce_session_timeout(
            int(os.getenv("UTS_SESSION_TIMEOUT_MINUTES", "30"))
        ):
            if request.path.startswith("/api/") or request.is_json:
                abort(401)
            return redirect(url_for("web.login", next=request.path))
        return None

    @app.context_processor
    def inject_security_context():
        from webapp.worker_service import find_online_worker

        user = current_user()
        worker = find_online_worker(user.id) if user else None
        return {
            "current_user": user,
            "is_admin": is_administrator(user),
            "can": lambda module, action="view": has_permission(user, module, action),
            "platform_modules": PLATFORM_MODULES,
            "csrf_token": lambda: session.get("csrf_token", ""),
            "my_worker": worker,
        }

    @app.errorhandler(403)
    def forbidden(_error):
        if request.path.startswith("/api/") or request.is_json:
            return {"error": "Access Denied"}, 403
        return render_template("403.html"), 403

    @app.errorhandler(400)
    def bad_request(error):
        if request.path.startswith("/api/") or request.is_json:
            return {"error": getattr(error, "description", "Bad Request")}, 400
        return error

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; connect-src 'self'",
        )
        if session.get("user_id"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
