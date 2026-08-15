# UTS — local build handoff

Working notes for taking the UTS automation platform off the shared VPS and
running it locally. Everything here was verified on 15 Aug 2026 against the live
system at `http://144.91.113.113:5050`, signed in as `JackTest` (Administrator).

**If you are a new session picking this up: read "Start here" then "How to run it
locally". The rest is reference.**

---

## Start here

### What is in this folder

| Path | What it is |
|---|---|
| `uts-platform/` | The complete UTS application — 1,328 files, 6.3 MB. Pulled from the connector install at `%LOCALAPPDATA%\UTS-Worker`. |
| `UTS-Connect-JackTest.bat` | The broken installer as downloaded from the server. Kept as evidence — it has LF line endings on purpose. Do not "fix" it. |
| `UTS-Connect-JackTest-FIXED.bat` | Corrected installer, verified end to end. |
| `.gitignore` | Keeps `runtime/`, `web-data/`, `.env` and databases out of git. |

### The single most important fact

**`uts-platform/` is not a worker. It is the entire platform.** The server hands
out `worker-package.zip`, which `build_worker_package_bytes()` builds by walking
the *whole* repository, excluding only secrets, the venv and `*.db`. So this
folder contains the Flask web app, all 13 templates, the automation engine, the
API farm and the worker agent — everything the VPS runs.

There is nothing to port and nothing to rewrite. It already runs locally; this
was confirmed by starting it on port 5060 and getting a 200 with a fully
initialised database (16 tables, 6 roles, 125 permissions).

### What is deliberately missing

- **`uts-platform/runtime/`** — the portable Python 3.12.10 (96.6 MB, 4,009
  files). Excluded from git. Get it back by re-running the fixed connector, or
  by downloading `http://144.91.113.113:5050/download/portable-python-win64.zip`
  (no auth needed), or skip it entirely and use a normal venv.
- **`uts-platform/web-data/`** — contains `worker-token.json`, a live Bearer
  token for the UTS account. Excluded on purpose.
- **The production database.** A local instance starts *empty*. The 18 projects,
  269 modules, 223 UI objects and 26 executions live in the VPS's
  `web-data/uts_platform.db`, and `.db` files are excluded from the package.
  Migrating real data means copying that one file off the VPS.

---

## How to run it locally

### Option A — portable runtime (no system Python needed)

Requires `uts-platform/runtime/` to be present (see above).

There is one blocker: **`run_web.py` fails under the embedded Python** with
`ModuleNotFoundError: No module named 'webapp'`. The embeddable distribution
ships a `python312._pth` file, which stops Python adding the script's directory
to `sys.path`. `worker/agent.py` already works around this with an explicit
`sys.path.insert(0, str(ROOT))`; `run_web.py` is simply missing that line.

Either add it to `run_web.py`, or use a bootstrap file:

```python
# _boot.py, next to run_web.py
import sys, runpy, pathlib
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "run_web.py"), run_name="__main__")
```

```bat
set UTS_PORT=5060
set UTS_HOST=127.0.0.1
set UTS_OPEN_BROWSER=false
set DATABASE_URL=sqlite:///web-data/uts_platform.db
set UTS_ADMIN_USERNAME=localadmin
set UTS_ADMIN_PASSWORD=<choose one>
set UTS_SECRET_KEY=<long random string>
runtime\python.exe _boot.py
```

All required packages are already installed in the portable runtime —
Flask 3.1.3, Flask-SQLAlchemy, SQLAlchemy 2.0.52, Selenium 4.47, openpyxl,
python-dotenv, PyMySQL. Nothing to pip install.

### Option B — system Python

`RUN-WEB.bat` and `run-web.sh` ship in `uts-platform/` and exist for exactly
this. They find Python, build a `.venv`, pip install `requirements.txt`, force
`DATABASE_URL` to local SQLite, and start `run_web.py`. `run-web.sh` says so in
its header: *"Each user runs this on their own machine, so the automation
browser opens locally on that same machine."*

Verified working configuration (Option A, 15 Aug):

```
Local URL:   http://127.0.0.1:5060
 * Serving Flask app 'webapp'
Status : 200   Title : UTS
tables (16) — access_role, audit_log, business_flow, client_machine, execution,
execution_step, module, page, project, role_permission, scan_history, test_case,
ui_object, user, worker_agent, worker_job
roles: Administrator, Executive, Manager, Supervisor, TestUser, Viewer
```

### What you gain and lose locally

**Gain:** no internet exposure, no connection starvation, no unauthenticated
source download, and the API farm can finally reach LAN / VPN / localhost
endpoints the VPS cannot see. Since the browser already runs on your machine,
**testing itself loses nothing.**

**Lose:** the multi-user side — shared project database, RBAC across nine
accounts, the audit log, and other testers queueing jobs to their own PCs.

---

## Architecture in brief

Two tiers. The **server** is the control plane and the only durable storage. The
**worker** is a browser execution surface. Critically, the server is a *peer*,
not a coordinator — choosing "Server" in the UI runs the identical code with
Chrome on the VPS.

- The worker **never accepts inbound connections.** It polls
  `POST /api/worker/heartbeat` and `GET /api/worker/next-job` every 3 seconds.
  No port forwarding or fixed IP is needed on the client.
- Two auth schemes hit the same Flask app: the browser uses a session cookie
  plus a CSRF token; the agent uses a Bearer token and is explicitly exempted
  from the CSRF/session hook in `_register_security_hooks()`.
- Worker tokens are `secrets.token_urlsafe(32)`, stored server-side as a SHA-256
  hash, cached client-side in cleartext at `web-data/worker-token.json`. They
  never expire.
- A worker counts as online for 90 seconds after its last heartbeat
  (`ONLINE_WINDOW_SECONDS`).

### Job types

`MODULES` (scan) · `FLOW` (generate) · `EXECUTION` · `STORED_EXECUTION` ·
`PIPELINE`

### Where the browser opens

The radio buttons are named `run_location_choice`, which **the server never
reads**. A `data-run-location-sync` submit handler copies the value into a
`run_location` field at submit time. `_parse_run_location()` accepts only
`local` or `server`; anything else — including a missing field if that
JavaScript never runs — falls back to "local if this user has a worker seen in
the last 90s, else server". So the choice silently depends on client-side JS,
but degrades safely.

### Where test cases come from

Not from the scan. The **Generate** step (`FLOW`) deep-crawls selected modules,
maps pages and elements, and the offline rule-based planner
(`UTS_AI_PROVIDER=offline` by default — no external AI service is called) turns
what it saw into scenarios. `persist_discovery()` converts each scenario into
one `business_flow` row and one `test_case` row, storing steps twice:
`manual_steps` for humans, `automation_steps` with locators for replay.

Test cases are only as good as the crawl. In project 18, most of the 25 modules
sit at `0 pages · 0 flows` and therefore yield nothing.

### Where results go

The agent's `_collect_artifacts()` uploads **exactly four things**:
`modules.json`, `discovered-flow.json`, `page-map.json`,
`latest-e2e-report.html`. The server writes them to disk, parses them into
SQLite, then `_archive()` copies `generated/` and `reports/` into
`web-data/projects/<project_id>/run-<history_id>/`.

---

## Known bugs

### Installer / batch scripts

All four connector defects originate in `webapp/worker_installer.py`, which
builds the `.bat` from a Python f-string and serves it verbatim.

| # | Defect | Effect |
|---|---|---|
| 1 | LF-only line endings | `cmd` seeks assuming CRLF, drifts one byte per line, executes garbage. Exit 255. |
| 2 | Unescaped `)` in `echo pip install failed (Access denied ...)` inside an `if` block | Closes the block early; stray `.` → `. was unexpected at this time.` **Parse error, so it fires even when the branch is not taken** — the install completes through pip then dies before writing `worker.env`. |
| 3 | Nested double quotes in the `Get-CimInstance` call | Flips `cmd`'s quote state so `^\|` reaches PowerShell literally → parameter binding error. The "stop old worker" step has never worked. |
| 4 | Em dashes / middle dot (non-ASCII) | Mojibake under the console code page; worsens defect 1's drift. |

Upstream fix in `build_oneclick_bat()`: escape as `^(` / `^)`, drop non-ASCII,
rewrite the PowerShell call without nested quotes, and
`return content.replace("\n", "\r\n")`. The macOS `.sh` branch is unaffected —
LF is correct there.

Latent, in files shipped inside the package:

- **`INSTALL-AUTO-WORKER.bat`** — same defect 2 pattern in
  `echo Scheduled task skipped (needs Admin). Startup folder is enough.` Only
  bites when `schtasks` fails, i.e. when not running as Admin — the common case.
- **`RUN-WORKER.bat`** — `if not "%A%"=="" if not "%B%"=="" (...) else (...)`
  binds the `else` to the *inner* `if`. With no `worker.env`, the outer test is
  false and **neither branch runs**; the script prints its banner and exits
  without starting the agent.
- **`RUN-WORKER.bat`** — the server-URL prompt discards input.
  `%UTS_SERVER_URL%` is substituted at parse time, so the following test always
  sees the pre-prompt value and overwrites what you typed with the default.
- **`run_web.py`** — missing `sys.path.insert`, see Option A above.

### Platform

- **`ExecutionStep` is never written.** The table is defined with fields for
  step name, status, duration and screenshot, and there is **not one line of
  code anywhere that inserts a row**. No step-level history exists for local or
  server runs.
- **Pass/fail counts for local runs are approximate.**
  `_complete_execution()` reads `reports/e2e-results-*.json` for real per-test
  totals — a file the worker never uploads. For a local run the server falls
  back to the exit code alone: all passed, or none did. The HTML report is
  accurate; the execution row's numbers are not.
- **ALM and Xpedite exports never leave the worker.** `_archive()` copies
  `alm-output/` and `xpedite-output/` from the *server's* folders, which after a
  local run are empty or stale. The 63 Xpedite files and `ALM_TestCases.xml`
  from 14 Aug exist only on the local machine.
- **API farm reports are not per-user.** Collections are correctly scoped as
  `web-data/api-farm/user-<id>.json`, but `api_farm_run()` writes a single
  shared `latest-api-report.html` and `api_farm_report()` serves that same file
  to everyone — so testers overwrite each other's reports and can read each
  other's response bodies, including tokens.
- **"Client PCs" does not reflect reality.** It reads `client_machine` (rows an
  admin types by hand), never joined to `worker_agent`. A live heartbeating
  worker does not appear there at all.
- **Nothing about testing is audited.** `record_audit()` is called only from
  `admin_routes.py`, `rbac.py` (access denials) and the login/logout block of
  `routes.py`. Creating or deleting a project, running a scan, executing a suite
  or running the API farm leave **no audit record**.

### Deployment (VPS only — these go away locally)

- `/download/worker-package.zip` and `/download/portable-python-win64.zip` have
  **no `@login_required`**. The full application source is downloadable by
  anyone who can reach port 5050. Confirmed with an unauthenticated 200.
- Werkzeug's dev server faces the internet directly over plain HTTP — no nginx,
  no TLS. Worker registration passwords and Bearer tokens cross the network in
  the clear.
- **Connection starvation.** 12 rapid TCP connects gave 2 successes and 10
  timeouts, though the successes answered in 127–186 ms. Port 22 and ICMP died
  at the same time and traceroute stopped past Telia's backbone, so packets are
  dropped at the host/provider edge. After 60 s of quiet, 6 probes at 20 s
  spacing were 6/6 OK. Contributing causes: `Connection: close` (no keep-alive,
  so every request is a fresh handshake), thread-per-connection on a dev server,
  and server-side Selenium running in a `ThreadPoolExecutor(max_workers=2)`
  **inside the same process** as the web server.
- `_ensure_admin_user()` defaults to `admin`/`admin` and re-applies the
  environment password on **every boot** unless `UTS_SYNC_ADMIN_PASSWORD=false`,
  clearing lockout counters as it goes. `UTS_SECRET_KEY` defaults to
  `change-this-before-production`.
- The audit log shows `FAILED_LOGIN` attempts from `51.195.24.96` (14 Aug), an
  external host unrelated to the team's addresses.

---

## Verified end-to-end run

Proof the dispatch loop closes, from the live system on 15 Aug:

| Time | Where | Observed |
|---|---|---|
| 10:51:38 | browser | `POST /projects/18/scan` with `run_location=local` |
| 10:51:39 | server | Redirect to `?job=141`; *"Scan queued on your PC (DESKTOP-9VOV15U)"* |
| 10:51:41 | local PC | `chromedriver` pid 11132 starts |
| 10:51:41 | UI | *"Opening browser on this machine (DESKTOP-9VOV15U)"* |
| 10:51:59 | local PC | `modules.json`, `discovered-flow.json`, `common-actions.json` written |
| ~10:52:00 | server | `/api/scans/141` → `{"status":"COMPLETED","module_count":25}` |

Click to browser was ~3 s, matching the poll interval. The completion string is
verbatim from `agent.py`, so it can only have come from the local machine.

---

## Suggested next steps

1. **Get `runtime/` back**, or create a venv, and stand the platform up locally
   on a chosen port. Apply the `run_web.py` `sys.path` fix as the first commit.
2. **Decide on data.** Blank local instance, or copy
   `web-data/uts_platform.db` off the VPS to bring the 18 projects across.
3. **Fix the batch scripts at source** in `webapp/worker_installer.py` so
   future connector downloads work, plus the two `RUN-WORKER.bat` bugs and
   `INSTALL-AUTO-WORKER.bat`.
4. **Decide the VPS's future** — retire it in favour of local, or fix the
   deployment (nginx + TLS, gunicorn, auth on the download endpoints, browser
   runs moved out of the web process).
5. **Close the reporting gaps** — upload `e2e-results-*.json` so pass/fail is
   real, write `ExecutionStep` rows, scope API farm reports per user, and add
   `record_audit()` to the project and execution routes.

## Open questions

- Is the VPS shared with other active users right now? Nine accounts exist and
  the dashboard shows projects owned by eight of them, so retiring it is not
  purely your call.
- Is a local instance meant to replace the VPS, or run alongside it?
- Does anyone rely on the ALM / Xpedite exports? They currently only ever exist
  on whichever machine ran the test.

## Reference

Two detailed write-ups produced alongside this work:

- **UTS Connector Teardown** — installer forensics, architecture, signed-in
  review of every module, risk list.
  <https://claude.ai/code/artifact/1d8e805b-7cf7-47dd-96ef-9431c457af20>
- **Server or My PC** — process flow diagrams: what runs where, where test cases
  come from, where results are stored.
  <https://claude.ai/code/artifact/9dcf0e90-be5c-48ec-9897-1a2663845b73>
