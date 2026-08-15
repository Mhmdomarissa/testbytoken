# UTS Automation Platform

The web platform is a control plane around the existing UTS scanner and
automation engine. The existing `RUN.bat` two-cycle CLI flow remains available.

## Implemented flow

1. Sign in to the UTS platform.
2. Create a project with URL, optional application credentials, browser, and name.
3. Click **Scan application** to launch the application locally and discover modules.
4. Select modules using checkboxes, Select All, or Deselect All.
5. Generate business flows, navigation paths, pages, UI objects, locators, manual
   steps, automation steps, ALM, and Xpedite artifacts.
6. Select generated test cases and click **Run automation**.
7. Watch live status and open the saved HTML report.
8. Re-scan projects to update the repository; duplicate objects are merged and
   locator changes are retained as alternatives.

## First-time setup

Requirements:

- Windows 10/11
- Python 3.10+
- MySQL 8+
- Chrome, Edge, or Firefox

Steps:

1. Double-click `SETUP.bat`.
2. In MySQL Workbench or the MySQL command line, execute:

   `database/setup-mysql.sql`

3. Open `.env` (created by setup) and change:

   - `DATABASE_URL`
   - `UTS_SECRET_KEY`
   - `UTS_ADMIN_USERNAME`
   - `UTS_ADMIN_PASSWORD`

4. Double-click `RUN-WEB.bat`.
5. Open `http://127.0.0.1:5050`.

The first start creates all MySQL tables and the configured administrator.

## Access from another machine on the same network

1. On the UTS server machine, run `ALLOW-NETWORK-ACCESS.bat` once as
   Administrator.
2. Start the platform using `RUN-WEB.bat`.
3. From another machine on the same private network, open:

   `http://192.168.1.94:5050`

The application binds to `0.0.0.0`, while `UTS_PUBLIC_URL` in `.env` controls
the address displayed and opened locally. If the server IP changes, update
`UTS_PUBLIC_URL`. Do not expose port 5050 directly to the public internet.

## Data stored in MySQL

- Users and projects
- Application URL, credentials, and browser setting
- Modules and selection state
- Pages, paths, types, summaries, and parent paths
- Business flows and user actions
- UI objects and object types
- Primary and alternate locators
- Locator stability score, duplicate fingerprint, and change count
- Manual and automation-ready test steps
- Scan history and artifact locations
- Execution history, status, totals, and report locations

## Generated files

Every flow scan/execution is archived under:

`web-data/projects/<project-id>/run-<history-id>/`

The archive can include:

- `generated/discovered-flow.json`
- `generated/page-map.json`
- `reports/*.html`
- `alm-output/`
- `xpedite-output/`

## Architecture

- `webapp/routes.py` — authentication, project CRUD, jobs, status APIs, reports
- `webapp/models.py` — MySQL relational model
- `webapp/uts_service.py` — bridge to the existing UTS engine and persistence
- `webapp/templates/` — HTML dashboard
- `webapp/static/` — responsive UI and live job polling
- `run_web.py` / `RUN-WEB.bat` — local web server
- `dynamic/`, `automation/`, `alm/`, `xpedite/` — existing reusable engine

## Current AI-assisted repository behavior

The repository applies deterministic AI-ready heuristics:

- IDs and names receive the highest locator stability scores.
- CSS and XPath locators are scored lower when they use indexes, `contains()`,
  or long brittle paths.
- Duplicate objects are merged using a fingerprint.
- Changed locators update the object and preserve recent previous locators.

An external LLM can be enabled in `config/ai.json` / `.env`:

- `UTS_AI_PROVIDER=offline` (default) — built-in planner covering link, object,
  enter/sendKeys, verification, data-driven, and BDD with no API key
- `UTS_AI_PROVIDER=openai|ollama|azure_openai` — live LLM understanding
- CLI: `RUN-AI.bat` or `python run_ai.py --modules Admin --run`
- Web generate/run-all uses `ai_mode=true` automatically

Artifacts written under `generated/`:

- `ai-plan.json` — AI understanding summary
- `object-repository.json` — objects + locators
- `bdd/*.feature` — Gherkin BDD
- `AI_TestData.xlsx` — data-driven sheets
- `discovered-flow.json` — executable scenarios

## Execution note

Browser automation runs on the same machine as the web server. A process lock
prevents two Selenium scans from controlling the local browser simultaneously.
Web jobs remain asynchronous so the dashboard stays responsive.

## Future adapters

The database uses generic project, flow, object, test, and execution entities.
Desktop, Mobile, and API adapters can be introduced alongside the current web
adapter. The planned tool targets are Playwright, Appium, JMeter, and API clients.
