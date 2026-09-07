"""HTTP routes for the UTS dashboard."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from webapp.models import Execution, Module, Project, ScanHistory, TestCase, UIObject, User, db
from webapp.rbac import (
    current_user,
    has_permission,
    permission_required,
    projects_visible_to,
    record_audit,
    require_project_access,
    user_has_any_view_permission,
)
from webapp.uts_service import (
    create_manual_test_case,
    run_full_pipeline,
    run_generation,
    run_module_scan,
    run_stored_test_cases,
    scenarios_from_test_cases,
    stop_running_jobs,
)
from webapp.worker_service import enqueue_job, find_online_worker, request_stop_for_user


bp = Blueprint("web", __name__)
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="uts-web")


def _get_project(project_id: int) -> Project:
    """Load a project the current user is allowed to access."""
    project = db.get_or_404(Project, project_id)
    require_project_access(current_user(), project)
    return project


def _group_test_cases_by_module(
    modules: list[Module], test_cases: list[TestCase]
) -> list[dict]:
    """Group test cases under their module for the project page."""
    buckets: dict[int | None, list[TestCase]] = {}
    for case in test_cases:
        module_id = case.module_id
        if not module_id and case.flow and case.flow.module_id:
            module_id = case.flow.module_id
        buckets.setdefault(module_id, []).append(case)

    groups: list[dict] = []
    for module in modules:
        cases = sorted(buckets.pop(module.id, []), key=lambda item: item.name.lower())
        if cases:
            groups.append({"module": module, "cases": cases})

    orphan: list[TestCase] = []
    for cases in buckets.values():
        orphan.extend(cases)
    if orphan:
        groups.append(
            {
                "module": None,
                "cases": sorted(orphan, key=lambda item: item.name.lower()),
            }
        )
    return groups


def _parse_run_location() -> str:
    """Form field run_location: local (user PC) or server."""
    loc = (request.form.get("run_location") or "").strip().lower()
    if loc in ("local", "server"):
        return loc
    user = current_user()
    if user and find_online_worker(user.id):
        return "local"
    return "server"


def _local_worker_missing_flash() -> None:
    flash(
        "Local worker is not online. Run the connector on your PC, "
        "or choose Server under “Where should the browser run?”",
        "error",
    )


def _fail_history(history: ScanHistory | None, message: str) -> None:
    if not history:
        return
    history.status = "FAILED"
    history.message = message
    history.completed_at = datetime.utcnow()
    db.session.commit()


def _fail_execution(execution: Execution | None, message: str) -> None:
    if not execution:
        return
    execution.status = "FAILED"
    execution.message = message
    execution.current_step = message
    execution.completed_at = datetime.utcnow()
    db.session.commit()


def _authorized_home() -> str:
    user = current_user()
    choices = (
        ("projects", "web.dashboard"),
        ("api_farm", "web.api_farm"),
        ("user_management", "admin.users"),
        ("role_management", "admin.roles"),
        ("audit_logs", "admin.audit_logs"),
    )
    for module, endpoint in choices:
        if has_permission(user, module, "view"):
            return url_for(endpoint)
    return url_for("web.no_access")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            session.clear()
            return redirect(url_for("web.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _submit(function, *args) -> None:
    app = current_app._get_current_object()

    def invoke():
        with app.app_context():
            function(*args)

    executor.submit(invoke)


@bp.get("/")
def index():
    if session.get("user_id"):
        return redirect(_authorized_home())
    return redirect(url_for("web.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        language = request.form.get("language", "en").strip() or "en"
        user = User.query.filter(db.func.lower(User.username) == username.lower()).first()
        now = datetime.utcnow()

        if user and user.locked_until and user.locked_until > now:
            record_audit(
                "FAILED_LOGIN",
                "authentication",
                target=user,
                remarks="Login rejected: account temporarily locked",
                commit=True,
            )
            flash("Account temporarily locked after repeated failed attempts. Try again later.", "error")
            return render_template("login.html"), 423

        if not user or user.is_deleted or not check_password_hash(user.password_hash, password):
            if user and not user.is_deleted:
                user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= 5:
                    user.locked_until = now + timedelta(minutes=15)
                record_audit(
                    "FAILED_LOGIN",
                    "authentication",
                    target=user,
                    remarks=f"Invalid credentials (attempt {user.failed_login_attempts})",
                )
                db.session.commit()
            else:
                record_audit(
                    "FAILED_LOGIN",
                    "authentication",
                    remarks=f"Unknown or deleted username: {username}",
                    commit=True,
                )
            flash("Invalid username or password.", "error")
            return render_template("login.html"), 401

        if not user.is_active:
            record_audit(
                "FAILED_LOGIN",
                "authentication",
                target=user,
                remarks="Login rejected: inactive account",
                commit=True,
            )
            flash("Your account is inactive. Please contact the Administrator.", "error")
            return render_template("login.html"), 403

        csrf_token = session.get("csrf_token", "")
        session.clear()
        session["csrf_token"] = csrf_token
        session["user_id"] = user.id
        session["username"] = user.username
        session["role"] = user.access_role.name if user.access_role else user.role
        session["session_version"] = int(user.session_version or 1)
        session["language"] = language
        session["last_activity"] = now.isoformat()
        session.permanent = True
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        record_audit("LOGIN", "authentication", actor=user, remarks="Successful login")
        db.session.commit()

        if not user_has_any_view_permission(user):
            flash(
                "Your role has no module access yet. Ask an Administrator to assign permissions.",
                "error",
            )
            return redirect(url_for("web.no_access"))

        next_url = request.args.get("next", "")
        if next_url and not urlsplit(next_url).netloc and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(_authorized_home())
    return render_template("login.html")


@bp.get("/no-access")
@login_required
def no_access():
    user = current_user()
    if user and user_has_any_view_permission(user):
        return redirect(_authorized_home())
    return render_template("no_access.html")


@bp.post("/logout")
def logout():
    user = current_user()
    if user:
        record_audit("LOGOUT", "authentication", actor=user, remarks="User signed out", commit=True)
    session.clear()
    return redirect(url_for("web.login"))


@bp.get("/dashboard")
@login_required
@permission_required("projects", "view")
def dashboard():
    user = current_user()
    visible = projects_visible_to(user)
    projects = visible.order_by(Project.updated_at.desc()).all()
    project_ids = [project.id for project in projects]
    creator_ids = {project.created_by for project in projects}
    project_creators = (
        {
            row.id: row.username
            for row in User.query.filter(User.id.in_(creator_ids)).all()
        }
        if creator_ids
        else {}
    )
    totals = {
        "projects": len(projects),
        "modules": Module.query.filter(Module.project_id.in_(project_ids)).count()
        if project_ids
        else 0,
        "objects": UIObject.query.filter(UIObject.project_id.in_(project_ids)).count()
        if project_ids
        else 0,
        "executions": Execution.query.filter(Execution.project_id.in_(project_ids)).count()
        if project_ids
        else 0,
    }
    return render_template(
        "dashboard.html",
        projects=projects,
        totals=totals,
        project_creators=project_creators,
    )


@bp.get("/download/worker-package.zip")
def download_worker_package_zip():
    """Public portable worker code zip (no secrets) for one-click PC install."""
    from webapp.worker_package import build_worker_package_bytes

    data = build_worker_package_bytes()
    return Response(
        data,
        mimetype="application/zip",
        headers={"Content-Disposition": 'attachment; filename="UTS-Worker-Package.zip"'},
    )


@bp.get("/download/portable-python-win64.zip")
def download_portable_python():
    """Bundled Python 3.12 + pip so other PCs do not need system Python."""
    path = Path(current_app.root_path).parent / "web-data" / "portable-python-win64.zip"
    if not path.is_file():
        try:
            from tools.prepare_portable_python import prepare

            prepare(force=False)
        except Exception as exc:  # noqa: BLE001
            abort(503, description=f"Portable Python not available: {exc}")
    if not path.is_file():
        abort(503, description="Portable Python zip missing on server.")
    return send_file(
        path,
        mimetype="application/zip",
        as_attachment=True,
        download_name="portable-python-win64.zip",
    )


@bp.get("/download/install-auto-worker")
@login_required
def download_install_auto_worker():
    """One-click installer: .bat (Windows) or .sh (macOS)."""
    from webapp.worker_installer import is_mac_user_agent, worker_installer_for_platform

    user = current_user()
    server_url = (request.url_root or "").rstrip("/")
    username = (user.username if user else session.get("username") or "admin").strip()
    platform = request.args.get("platform", "")
    if not platform and is_mac_user_agent(request.headers.get("User-Agent", "")):
        platform = "mac"
    filename, content = worker_installer_for_platform(
        server_url=server_url, username=username, platform=platform
    )
    return Response(
        content,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.get("/download/install-auto-worker-mac")
@login_required
def download_install_auto_worker_mac():
    """Explicit macOS one-click worker installer."""
    from webapp.worker_installer import build_oneclick_sh

    user = current_user()
    server_url = (request.url_root or "").rstrip("/")
    username = (user.username if user else session.get("username") or "admin").strip()
    filename, content = build_oneclick_sh(server_url=server_url, username=username)
    return Response(
        content,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.post("/projects")
@login_required
@permission_required("projects", "create")
def create_project():
    name = request.form.get("name", "").strip()
    url = request.form.get("application_url", "").strip()
    if not name or not url:
        flash("Project name and application URL are required.", "error")
        return redirect(url_for("web.dashboard"))
    project = Project(
        name=name,
        application_url=url,
        app_username=request.form.get("app_username", "").strip(),
        app_password=request.form.get("app_password", ""),
        app_role=request.form.get("app_role", "").strip(),
        browser=request.form.get("browser", "chrome"),
        created_by=session["user_id"],
    )
    db.session.add(project)
    db.session.commit()
    flash("Project created.", "success")
    return redirect(url_for("web.project_detail", project_id=project.id))


@bp.get("/projects/<int:project_id>")
@login_required
@permission_required("projects", "view")
def project_detail(project_id: int):
    project = _get_project(project_id)
    modules = Module.query.filter_by(project_id=project.id).order_by(Module.name).all()
    test_cases = TestCase.query.filter_by(project_id=project.id).order_by(TestCase.name).all()
    test_cases_by_module = _group_test_cases_by_module(modules, test_cases)
    scans = (
        ScanHistory.query.filter_by(project_id=project.id)
        .order_by(ScanHistory.created_at.desc())
        .limit(10)
        .all()
    )
    executions = (
        Execution.query.filter_by(project_id=project.id)
        .order_by(Execution.created_at.desc())
        .limit(10)
        .all()
    )
    objects = (
        UIObject.query.filter_by(project_id=project.id)
        .order_by(UIObject.stable_score.desc(), UIObject.name)
        .limit(100)
        .all()
    )
    return render_template(
        "project.html",
        project=project,
        modules=modules,
        test_cases=test_cases,
        test_cases_by_module=test_cases_by_module,
        scans=scans,
        executions=executions,
        objects=objects,
    )


@bp.post("/projects/<int:project_id>/edit")
@login_required
@permission_required("projects", "edit")
def edit_project(project_id: int):
    project = _get_project(project_id)
    project.name = request.form.get("name", project.name).strip()
    project.application_url = request.form.get("application_url", project.application_url).strip()
    project.app_username = request.form.get("app_username", "").strip()
    project.app_role = request.form.get("app_role", "").strip()
    password = request.form.get("app_password", "")
    if password:
        project.app_password = password
    project.browser = request.form.get("browser", project.browser)
    db.session.commit()
    flash("Project updated.", "success")
    return redirect(url_for("web.project_detail", project_id=project.id))


@bp.post("/projects/<int:project_id>/delete")
@login_required
@permission_required("projects", "delete")
def delete_project(project_id: int):
    project = _get_project(project_id)
    name = project.name

    # Clear project-scoped rows that may not cascade automatically.
    TestCase.query.filter_by(project_id=project.id).delete(synchronize_session=False)
    UIObject.query.filter_by(project_id=project.id).delete(synchronize_session=False)
    execution_ids = [
        row[0]
        for row in db.session.query(Execution.id).filter_by(project_id=project.id).all()
    ]
    if execution_ids:
        from webapp.models import ExecutionStep

        ExecutionStep.query.filter(ExecutionStep.execution_id.in_(execution_ids)).delete(
            synchronize_session=False
        )

    artifact_root = Path(current_app.config["UTS_ROOT"]) / "web-data" / "projects" / str(project.id)
    db.session.delete(project)
    db.session.commit()

    if artifact_root.exists():
        import shutil

        shutil.rmtree(artifact_root, ignore_errors=True)

    flash(f'Project "{name}" deleted.', "success")
    return redirect(url_for("web.dashboard"))


@bp.post("/projects/<int:project_id>/scan")
@login_required
@permission_required("projects", "execute")
def scan_project(project_id: int):
    project = _get_project(project_id)
    user = current_user()
    history = ScanHistory(project_id=project.id, scan_type="MODULES", status="QUEUED")
    db.session.add(history)
    db.session.commit()

    run_location = _parse_run_location()

    if run_location == "server":
        _submit(run_module_scan, project.id, history.id)
        flash("Scan started on the server.", "success")
    elif user and enqueue_job(
        user_id=user.id,
        project=project,
        job_type="MODULES",
        history_id=history.id,
    ):
        worker = find_online_worker(user.id)
        flash(
            f"Scan queued on your PC ({worker.machine_name}). Browser will open there.",
            "success",
        )
    else:
        _fail_history(history, "No local worker online")
        _local_worker_missing_flash()
    return redirect(url_for("web.project_detail", project_id=project.id, job=history.id))


@bp.post("/projects/<int:project_id>/generate")
@login_required
@permission_required("projects", "execute")
def generate_project(project_id: int):
    project = _get_project(project_id)
    module_ids = [int(value) for value in request.form.getlist("module_ids") if value.isdigit()]
    modules = Module.query.filter(Module.project_id == project.id, Module.id.in_(module_ids)).all()
    if not modules:
        flash("Select at least one discovered module.", "error")
        return redirect(url_for("web.project_detail", project_id=project.id))
    for module in Module.query.filter_by(project_id=project.id):
        module.selected = module in modules
    history = ScanHistory(project_id=project.id, scan_type="FLOW", status="QUEUED")
    db.session.add(history)
    db.session.commit()
    names = [module.name for module in modules]
    user = current_user()
    run_location = _parse_run_location()

    if run_location == "server":
        _submit(run_generation, project.id, history.id, names, False, None)
        flash("Flow discovery and test generation started on the server.", "success")
    elif user and enqueue_job(
        user_id=user.id,
        project=project,
        job_type="FLOW",
        history_id=history.id,
        selected_modules=names,
        execute=False,
    ):
        worker = find_online_worker(user.id)
        flash(f"Generate queued on your PC ({worker.machine_name}).", "success")
    else:
        _fail_history(history, "No local worker online")
        _local_worker_missing_flash()
    return redirect(url_for("web.project_detail", project_id=project.id, job=history.id))


@bp.post("/projects/<int:project_id>/test-cases")
@login_required
@permission_required("projects", "create")
def create_test_case(project_id: int):
    project = _get_project(project_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Test case name is required.", "error")
        return redirect(url_for("web.project_detail", project_id=project.id) + "#tests")
    case = create_manual_test_case(
        project,
        name=name,
        test_type=request.form.get("test_type", "automation"),
        steps_text=request.form.get("steps_text", ""),
        module_name=request.form.get("module_name", "Manual") or "Manual",
    )
    flash(f"Manual test case created: {case.external_key}", "success")
    return redirect(url_for("web.project_detail", project_id=project.id) + "?tab=tests")


@bp.post("/projects/<int:project_id>/execute")
@login_required
@permission_required("projects", "execute")
def execute_project(project_id: int):
    project = _get_project(project_id)
    module_ids = [int(value) for value in request.form.getlist("module_ids") if value.isdigit()]
    test_case_ids = [int(value) for value in request.form.getlist("test_case_ids") if value.isdigit()]
    modules = Module.query.filter(Module.project_id == project.id, Module.id.in_(module_ids)).all()
    cases = []
    if test_case_ids:
        cases = TestCase.query.filter(
            TestCase.project_id == project.id, TestCase.id.in_(test_case_ids)
        ).all()
        if not modules:
            selected_module_ids = {case.module_id for case in cases if case.module_id}
            modules = Module.query.filter(Module.id.in_(selected_module_ids)).all()

    if not modules and not cases:
        flash("Select a module or test case to execute.", "error")
        return redirect(url_for("web.project_detail", project_id=project.id))

    # Prefer running selected stored cases (AI-generated or manual) as-is.
    if cases:
        module_names = sorted(
            {
                *(module.name for module in modules),
                *(
                    (db.session.get(Module, case.module_id).name if case.module_id else "Manual")
                    for case in cases
                ),
            }
        )
        execution = Execution(
            project_id=project.id,
            module_names=module_names,
            test_case_ids=test_case_ids,
            status="QUEUED",
            current_step="Waiting for worker / browser",
            total=len(cases),
        )
        history = ScanHistory(project_id=project.id, scan_type="EXECUTION", status="QUEUED")
        db.session.add_all([execution, history])
        db.session.commit()

        user = current_user()
        run_location = _parse_run_location()
        names = module_names or ["Manual"]
        if run_location == "server":
            _submit(run_stored_test_cases, project.id, history.id, execution.id, test_case_ids)
            flash("Running selected test cases on the server.", "success")
        elif user and enqueue_job(
            user_id=user.id,
            project=project,
            job_type="STORED_EXECUTION",
            history_id=history.id,
            execution_id=execution.id,
            selected_modules=names,
            test_case_ids=test_case_ids,
            execute=True,
            stored_scenarios=[
                {
                    "id": s.id,
                    "type": s.type,
                    "title": s.title,
                    "module": s.module,
                    "steps": [
                        {
                            "step_no": st.step_no,
                            "action": st.action,
                            "object_name": st.object_name,
                            "input_value": st.input_value,
                            "locator_by": st.locator_by,
                            "locator_value": st.locator_value,
                            "expected": st.expected,
                        }
                        for st in s.steps
                    ],
                }
                for s in scenarios_from_test_cases(cases)
            ],
        ):
            worker = find_online_worker(user.id)
            flash(f"Automation queued on your PC ({worker.machine_name}).", "success")
        else:
            _fail_history(history, "No local worker online")
            _fail_execution(execution, "No local worker online")
            _local_worker_missing_flash()
        return redirect(url_for("web.project_detail", project_id=project.id, execution=execution.id))

    execution = Execution(
        project_id=project.id,
        module_names=[module.name for module in modules],
        test_case_ids=test_case_ids,
        status="QUEUED",
        current_step="Waiting for worker / browser",
    )
    history = ScanHistory(project_id=project.id, scan_type="EXECUTION", status="QUEUED")
    db.session.add_all([execution, history])
    db.session.commit()
    names = [module.name for module in modules]
    user = current_user()
    run_location = _parse_run_location()

    if run_location == "server":
        _submit(
            run_generation,
            project.id,
            history.id,
            names,
            True,
            execution.id,
        )
        flash("Automation started on the server.", "success")
    elif user and enqueue_job(
        user_id=user.id,
        project=project,
        job_type="EXECUTION",
        history_id=history.id,
        execution_id=execution.id,
        selected_modules=names,
        test_case_ids=test_case_ids,
        execute=True,
    ):
        worker = find_online_worker(user.id)
        flash(f"Automation queued on your PC ({worker.machine_name}).", "success")
    else:
        _fail_history(history, "No local worker online")
        _fail_execution(execution, "No local worker online")
        _local_worker_missing_flash()
    return redirect(url_for("web.project_detail", project_id=project.id, execution=execution.id))


@bp.post("/projects/<int:project_id>/run-all")
@login_required
@permission_required("projects", "execute")
def run_all_project(project_id: int):
    """Unified pipeline: generate positive/negative TCs, run automation, produce report."""
    project = _get_project(project_id)
    module_ids = [int(value) for value in request.form.getlist("module_ids") if value.isdigit()]
    modules = Module.query.filter(Module.project_id == project.id, Module.id.in_(module_ids)).all()
    if not modules:
        flash("Select at least one module for the full pipeline.", "error")
        return redirect(url_for("web.project_detail", project_id=project.id))

    for module in Module.query.filter_by(project_id=project.id):
        module.selected = module in modules

    execution = Execution(
        project_id=project.id,
        module_names=[module.name for module in modules],
        test_case_ids=[],
        status="QUEUED",
        current_step="Queued — scan, generate, run, report",
    )
    history = ScanHistory(project_id=project.id, scan_type="PIPELINE", status="QUEUED")
    db.session.add_all([execution, history])
    db.session.commit()
    names = [module.name for module in modules]
    user = current_user()
    run_location = _parse_run_location()

    if run_location == "server":
        _submit(
            run_full_pipeline,
            project.id,
            history.id,
            names,
            execution.id,
        )
        flash("Full pipeline started on the server.", "success")
    elif user and enqueue_job(
        user_id=user.id,
        project=project,
        job_type="PIPELINE",
        history_id=history.id,
        execution_id=execution.id,
        selected_modules=names,
        execute=True,
    ):
        worker = find_online_worker(user.id)
        flash(f"Full pipeline queued on your PC ({worker.machine_name}).", "success")
    else:
        _fail_history(history, "No local worker online")
        _fail_execution(execution, "No local worker online")
        _local_worker_missing_flash()
    return redirect(url_for("web.project_detail", project_id=project.id, execution=execution.id))


@bp.post("/projects/<int:project_id>/stop")
@login_required
@permission_required("projects", "execute")
def stop_project(project_id: int):
    """Stop running scan / generation / automation for this project."""
    _get_project(project_id)
    stopped = stop_running_jobs(project_id)
    user = current_user()
    remote = 0
    if user:
        remote = request_stop_for_user(user.id, project_id)
    wants_json = (
        request.accept_mimetypes.best == "application/json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.args.get("format") == "json"
    )
    if wants_json:
        return jsonify(
            ok=True,
            status="STOPPED",
            message="Stop requested — server and worker jobs marked stopped.",
            stopped=stopped,
            remote_jobs=remote,
        )
    flash("Stop requested. Browser closed / worker stop signal sent.", "success")
    return redirect(url_for("web.project_detail", project_id=project_id))


@bp.get("/api/scans/<int:history_id>")
@login_required
@permission_required("projects", "view")
def scan_status(history_id: int):
    item = db.get_or_404(ScanHistory, history_id)
    _get_project(item.project_id)
    return jsonify(
        id=item.id,
        status=item.status,
        message=item.message,
        module_count=item.module_count,
        page_count=item.page_count,
        object_count=item.object_count,
    )


@bp.get("/api/executions/<int:execution_id>")
@login_required
@permission_required("projects", "view")
def execution_status(execution_id: int):
    item = db.get_or_404(Execution, execution_id)
    _get_project(item.project_id)
    return jsonify(
        id=item.id,
        status=item.status,
        message=item.message,
        current_step=item.current_step,
        passed=item.passed,
        failed=item.failed,
        total=item.total,
        report_url=url_for("web.execution_report", execution_id=item.id)
        if item.report_path
        else "",
    )


@bp.get("/executions/<int:execution_id>/report")
@login_required
@permission_required("reports", "view")
def execution_report(execution_id: int):
    item = db.get_or_404(Execution, execution_id)
    _get_project(item.project_id)
    if not item.report_path:
        abort(404, description="No report file for this execution.")

    root = Path(current_app.config["UTS_ROOT"]).resolve()
    allowed_roots = (
        (root / "web-data").resolve(),
        (root / "reports").resolve(),
    )

    path = Path(item.report_path)
    # Prefer archived copy under web-data if the stored path is the live reports/ file.
    if path.name and not path.is_file():
        candidates = list((root / "web-data").rglob(path.name))
        if candidates:
            path = candidates[-1]
    try:
        path = path.resolve()
    except OSError:
        abort(404, description="Report path could not be resolved.")

    if not path.is_file():
        abort(404, description="Report file is missing on disk.")

    if not any(root_dir == path or root_dir in path.parents for root_dir in allowed_roots):
        abort(404, description="Report path is outside allowed folders.")

    return send_file(path)


# ---------------------------------------------------------------------------
# API Test Farm (direct HTTP testing — not UI Selenium)
# ---------------------------------------------------------------------------

def _api_collection_key() -> str:
    return f"user-{session.get('user_id') or 'guest'}"


@bp.get("/api-farm")
@login_required
@permission_required("api_farm", "view")
def api_farm():
    from api_farm.engine import load_collection

    collection = load_collection(_api_collection_key())
    return render_template(
        "api_farm.html",
        collection=collection,
        farm_role=session.get("role", "Tester"),
        farm_language=session.get("language", "en"),
    )


@bp.post("/api-farm/send")
@login_required
@permission_required("api_farm", "execute")
def api_farm_send():
    """Hit an API immediately and return JSON result (for the live tester)."""
    from api_farm.engine import load_collection, run_api_request
    from api_farm.normalize import normalize_request_payload

    payload = normalize_request_payload(request.get_json(silent=True) or {})
    url = str(payload.get("url") or "").strip()
    if not url:
        return jsonify(ok=False, error="URL is required"), 400

    headers = payload.get("headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers) if headers.strip() else {}
        except json.JSONDecodeError:
            return jsonify(ok=False, error="Headers must be valid JSON object"), 400

    collection = load_collection(_api_collection_key())
    variables = dict(collection.get("variables") or {})
    extra = payload.get("variables") or {}
    if isinstance(extra, dict):
        variables.update(extra)

    spec = {
        "id": payload.get("id") or "live",
        "name": payload.get("name") or "Live request",
        "method": payload.get("method") or "GET",
        "url": url,
        "headers": headers,
        "body": str(payload.get("body") or ""),
        "expected_status": int(payload.get("expected_status") or 200),
        "assertions": payload.get("assertions") or [],
        "auth": payload.get("auth") or {"type": "none"},
        "extractors": payload.get("extractors") or [],
    }
    result = run_api_request(spec, variables)
    # Persist newly extracted vars into collection for chaining in UI session
    if result.extracted:
        collection["variables"] = {**(collection.get("variables") or {}), **result.extracted}
        from api_farm.engine import save_collection

        save_collection(_api_collection_key(), collection)

    return jsonify(
        ok=result.status == "PASS",
        status=result.status,
        http_status=result.http_status,
        duration_ms=result.duration_ms,
        body=result.response_preview if len(result.response_preview) < 500 else result.response_preview,
        full_body=result.response_preview,
        error="" if result.status == "PASS" else result.message,
        messages=result.message.split("; ") if result.message else [],
        extracted=result.extracted,
        variables=result.variables_snapshot,
        resolved_url=result.url,
        normalized={
            "method": payload.get("method"),
            "url": payload.get("url"),
            "headers": payload.get("headers"),
            "body": payload.get("body"),
        },
    )


@bp.post("/api-farm/save")
@login_required
@permission_required("api_farm", "create")
def api_farm_save():
    """Save / update a request in the user's API collection."""
    import uuid

    from api_farm.engine import load_collection, save_collection

    payload = request.get_json(silent=True) or request.form
    name = str(payload.get("name") or "API Request").strip()
    method = str(payload.get("method") or "GET").upper()
    url = str(payload.get("url") or "").strip()
    if not url:
        flash("URL is required to save a request.", "error")
        if request.is_json:
            return jsonify(ok=False, error="URL required"), 400
        return redirect(url_for("web.api_farm"))

    headers = payload.get("headers") or {}
    if isinstance(headers, str):
        headers = json.loads(headers) if headers.strip() else {}
    body = str(payload.get("body") or "")
    expected_status = int(payload.get("expected_status") or 200)
    req_id = str(payload.get("id") or "").strip() or f"api_{uuid.uuid4().hex[:8]}"
    auth = payload.get("auth") or {"type": "none"}
    if isinstance(auth, str):
        auth = json.loads(auth) if auth.strip() else {"type": "none"}

    collection = load_collection(_api_collection_key())
    requests_list = list(collection.get("requests") or [])
    entry = {
        "id": req_id,
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "body": body,
        "expected_status": expected_status,
        "assertions": payload.get("assertions") or [],
        "tags": payload.get("tags") or ["positive"],
        "auth": auth,
        "extractors": payload.get("extractors") or [],
    }
    replaced = False
    for i, item in enumerate(requests_list):
        if item.get("id") == req_id:
            requests_list[i] = entry
            replaced = True
            break
    if not replaced:
        requests_list.append(entry)
    collection["requests"] = requests_list
    collection["name"] = collection.get("name") or "My API Collection"
    save_collection(_api_collection_key(), collection)

    if request.is_json:
        return jsonify(ok=True, id=req_id, count=len(requests_list))
    flash(f"Saved API request: {name}", "success")
    return redirect(url_for("web.api_farm"))


@bp.post("/api-farm/delete/<req_id>")
@login_required
@permission_required("api_farm", "delete")
def api_farm_delete(req_id: str):
    from api_farm.engine import load_collection, save_collection

    collection = load_collection(_api_collection_key())
    collection["requests"] = [r for r in (collection.get("requests") or []) if r.get("id") != req_id]
    save_collection(_api_collection_key(), collection)
    flash("API request deleted.", "success")
    return redirect(url_for("web.api_farm"))


@bp.post("/api-farm/run")
@login_required
@permission_required("api_farm", "execute")
def api_farm_run():
    """Run all saved API requests and write HTML report with pie chart."""
    from api_farm.engine import build_api_report_html, load_collection, run_api_suite

    collection = load_collection(_api_collection_key())
    specs = list(collection.get("requests") or [])
    if not specs:
        flash("Save at least one API request before running the suite.", "error")
        return redirect(url_for("web.api_farm"))

    # Optional: only selected IDs
    selected = request.form.getlist("request_ids") or (request.get_json(silent=True) or {}).get("request_ids")
    if selected:
        wanted = set(selected)
        specs = [s for s in specs if s.get("id") in wanted]

    suite = run_api_suite(specs, initial_variables=dict(collection.get("variables") or {}))
    # Persist chained variables after suite for next manual sends
    if suite.get("variables"):
        collection["variables"] = suite["variables"]
        from api_farm.engine import save_collection

        save_collection(_api_collection_key(), collection)
    reports_dir = Path(current_app.config["UTS_ROOT"]) / "web-data" / "api-farm" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"api-report-{stamp}.html"
    latest = reports_dir / "latest-api-report.html"
    html = build_api_report_html(collection.get("name") or "API Suite", suite)
    report_path.write_text(html, encoding="utf-8")
    latest.write_text(html, encoding="utf-8")
    results_json = reports_dir / f"api-results-{stamp}.json"
    results_json.write_text(json.dumps(suite, indent=2), encoding="utf-8")

    summary = suite["summary"]
    flash(
        f"API suite finished: {summary['passed']} passed, {summary['failed']} failed "
        f"(of {summary['total']}).",
        "success" if summary["failed"] == 0 else "error",
    )
    return redirect(url_for("web.api_farm_report"))


@bp.get("/api-farm/report")
@login_required
@permission_required("reports", "view")
def api_farm_report():
    path = Path(current_app.config["UTS_ROOT"]) / "web-data" / "api-farm" / "reports" / "latest-api-report.html"
    if not path.is_file():
        flash("No API report yet. Run the suite first.", "error")
        return redirect(url_for("web.api_farm"))
    return send_file(path)


@bp.post("/api-farm/import")
@login_required
@permission_required("api_farm", "import")
def api_farm_import():
    """Import OpenAPI/Swagger or Postman Collection JSON (file upload or pasted JSON)."""
    from api_farm.engine import load_collection, save_collection
    from api_farm.importer import detect_and_import

    base_url = (request.form.get("base_url") or "").strip()
    raw_text = (request.form.get("json_text") or "").strip()
    upload = request.files.get("file")
    if upload and upload.filename:
        raw_text = upload.read().decode("utf-8-sig", errors="replace")
    if not raw_text:
        flash("Provide a Postman/OpenAPI JSON file or paste JSON.", "error")
        return redirect(url_for("web.api_farm"))
    try:
        payload = json.loads(raw_text)
        kind, imported = detect_and_import(payload, base_url=base_url)
    except Exception as exc:  # noqa: BLE001
        flash(f"Import failed: {exc}", "error")
        return redirect(url_for("web.api_farm"))

    collection = load_collection(_api_collection_key())
    existing = list(collection.get("requests") or [])
    existing.extend(imported)
    collection["requests"] = existing
    collection["name"] = collection.get("name") or f"Imported ({kind})"
    save_collection(_api_collection_key(), collection)
    flash(f"Imported {len(imported)} {kind} request(s).", "success")
    return redirect(url_for("web.api_farm"))


@bp.post("/api-farm/generate-cases")
@login_required
@permission_required("api_farm", "create")
def api_farm_generate_cases():
    """Generate positive + negative variants for all (or one) saved requests."""
    from api_farm.cases import expand_collection_with_pos_neg, generate_positive_negative
    from api_farm.engine import load_collection, save_collection

    collection = load_collection(_api_collection_key())
    requests_list = list(collection.get("requests") or [])
    if not requests_list:
        flash("Save or import requests first.", "error")
        return redirect(url_for("web.api_farm"))

    only_id = (request.form.get("request_id") or "").strip()
    if only_id:
        base = next((r for r in requests_list if r.get("id") == only_id), None)
        if not base:
            flash("Request not found.", "error")
            return redirect(url_for("web.api_farm"))
        generated = generate_positive_negative(base)
        requests_list.extend(generated)
        flash(f"Generated {len(generated)} positive/negative case(s).", "success")
    else:
        before = len(requests_list)
        requests_list = expand_collection_with_pos_neg(requests_list)
        flash(f"Expanded collection: {before} → {len(requests_list)} request(s).", "success")

    collection["requests"] = requests_list
    save_collection(_api_collection_key(), collection)
    return redirect(url_for("web.api_farm"))


@bp.post("/api-farm/variables")
@login_required
@permission_required("api_farm", "edit")
def api_farm_variables():
    """Save collection-level parameters used by {{var}} placeholders."""
    from api_farm.engine import load_collection, save_collection

    payload = request.get_json(silent=True) or {}
    variables = payload.get("variables")
    if isinstance(variables, str):
        try:
            variables = json.loads(variables) if variables.strip() else {}
        except json.JSONDecodeError:
            flash("Variables must be valid JSON object.", "error")
            return redirect(url_for("web.api_farm"))
    if not isinstance(variables, dict):
        return jsonify(ok=False, error="variables must be an object"), 400

    collection = load_collection(_api_collection_key())
    collection["variables"] = {str(k): v for k, v in variables.items()}
    save_collection(_api_collection_key(), collection)
    if request.is_json:
        return jsonify(ok=True, variables=collection["variables"])
    flash("Parameters saved.", "success")
    return redirect(url_for("web.api_farm"))


@bp.post("/api-farm/reorder")
@login_required
@permission_required("api_farm", "edit")
def api_farm_reorder():
    """Reorder requests so login runs before dependent APIs."""
    from api_farm.engine import load_collection, save_collection

    payload = request.get_json(silent=True) or {}
    order = payload.get("order") or request.form.getlist("order")
    if not order:
        return jsonify(ok=False, error="order required"), 400
    collection = load_collection(_api_collection_key())
    by_id = {r.get("id"): r for r in (collection.get("requests") or [])}
    ordered = [by_id[i] for i in order if i in by_id]
    leftovers = [r for r in collection.get("requests") or [] if r.get("id") not in set(order)]
    collection["requests"] = ordered + leftovers
    save_collection(_api_collection_key(), collection)
    return jsonify(ok=True, count=len(collection["requests"]))

