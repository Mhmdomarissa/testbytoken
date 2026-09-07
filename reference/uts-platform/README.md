# UTS Test Automation Suite

## Run on each user's own machine (Option A)

Install UTS on each person's Mac/Windows so the automation browser opens on
that same machine.

**Windows**
1. Double-click `SETUP.bat` (one time)
2. Double-click `RUN-WEB.bat`
3. Open `http://127.0.0.1:5050`

**macOS / Linux**
1. `chmod +x setup.sh run-web.sh` (one time)
2. `./setup.sh` (one time)
3. `./run-web.sh`
4. Open `http://127.0.0.1:5050`

## Central server + browsers on B/C/D (Option B)

Keep UTS on machine **A** (server). On each user machine (**B/C/D**):

1. Copy this project (or pull the same folder)
2. Run setup once (`SETUP.bat` / `./setup.sh`)
3. Start the worker:
   - Windows: `RUN-WORKER.bat` → enter server URL e.g. `http://192.168.1.94:5050`
   - Mac: `chmod +x run-worker.sh && ./run-worker.sh`
4. Login with the **same UTS username** when prompted by the worker
5. Keep the worker window open
6. In any browser, open the server URL, login, Scan/Run

Result: Chrome opens on **that user's machine**, results go back to the server.
Top bar shows `Worker · machine-name` when connected.

## User Management & RBAC

The web platform includes database-backed role-based access control:

- **Users:** create, edit, activate/deactivate, soft delete, reset passwords, CSV import/export
- **Roles:** create, edit, clone, delete, and assign module/action permissions
- **Permissions:** View, Create, Edit, Delete, Approve, Export, Import, Print, Execute
- **Enforcement:** authorised navigation only, server-side checks on every protected page/API
- **Audit:** login, logout, failed login, users, roles, permissions, password resets, and access denials
- **Security:** scrypt password hashing, strong password policy, CSRF protection, idle session timeout,
  account lockout, security headers, and immediate session invalidation after access changes

After signing in as an Administrator, use **Users**, **Roles**, and **Audit** in the top navigation.
New installations use the administrator credentials configured by
`UTS_ADMIN_USERNAME` / `UTS_ADMIN_PASSWORD` in `.env`.

## Web Platform

The suite now includes a local HTML/MySQL platform for login, project
management, application scanning, module selection, object repository,
test generation, automation execution, live status, and reports.

Run `SETUP.bat`, configure `.env` and MySQL using
`database/setup-mysql.sql`, then double-click `RUN-WEB.bat`.

Full instructions: [WEB-PLATFORM.md](WEB-PLATFORM.md)

**Dynamic mode** — provide **URL + username + password**.

## How it works (new)

### First time
1. Edit `config/app-input.json` → `url`, `username`, `password`
2. Double-click **`RUN.bat`**
3. Choose **`1` First run / Refresh**
4. Tool reads **ALL modules** from the app menu, creates test cases, runs them, saves:
   - `generated/discovered-flow.json`
   - `generated/modules.json` ← module list for later reruns

### Later — rerun only one module
1. Double-click **`RUN.bat`** → choose **`3`**
   OR double-click **`RUN-MODULE.bat`**
2. Pick module by number or name, e.g. `1` or `Admin` or `Admin,PIM`
3. Only that module’s test cases run (login is included automatically)

### Non-interactive (no menu)
In `config/app-input.json`:
```json
"run_mode": "select",
"selected_modules": ["Admin"]
```
Or CLI:
```bat
python run_automation_only.py --mode select --modules Admin --non-interactive
python run_automation_only.py --mode discover --non-interactive
```

`run_mode` values: `menu` | `discover` | `all` | `select` | `export`

## Quick Start

### AI mode (recommended)

1. Set `url`, `username`, `password` in `config/app-input.json`
2. Double-click **`RUN-AI.bat`** (or `RUN.bat` with `"ai_mode": true`)
3. Cycle 1 scans modules; Cycle 2 AI builds:
   - **Link** navigation
   - **Object** repository
   - **Enter / SendKeys**
   - **Verification**
   - **Data-driven** (`generated/AI_TestData.xlsx`)
   - **BDD** (`generated/bdd/*.feature`)
4. Optional live LLM: set `UTS_AI_PROVIDER=openai` + `UTS_AI_API_KEY` in `.env`

### Classic mode

### 1. Edit input (only 3 fields required)

Open `config/app-input.json`:

```json
{
  "url": "https://your-application.com/login",
  "username": "your_user",
  "password": "your_password",
  "app_name": "My Application"
}
```

### 2. Run

Double-click **`RUN.bat`**

## What Happens Automatically

| Phase | Action |
|-------|--------|
| **Discover** | Opens URL, finds login fields, reads ALL modules/menus |
| **Create TCs** | One automation TC per module (+ login + post-login) |
| **Automation** | Runs Selenium tests |
| **Report** | HTML report + live steps in browser |
| **Xpedite** | Exports `TC_*.xml`, `BPW_*.xml`, `BC_*.xml`, `TestData.xlsx` |
| **Rerun** | Later pick one module from saved list — no full rediscovery |

## Folder Structure

```
UTS-Test-Automation-Suite/
├── RUN.bat                 ← Menu: discover all / rerun selected
├── RUN-MODULE.bat          ← Jump straight to module picker
├── RUN-STATIC.bat          ← Fixed SMART BANK scenarios
├── run_automation_only.py  ← Main engine
├── config/
│   ├── app-input.json      ← YOUR URL + username + password
│   ├── selenium.json       ← Browser settings
│   └── ...
├── dynamic/
│   ├── discovery.py        ← Scans page UI / modules
│   ├── module_selector.py  ← Module menu + filter
│   └── automation_runner.py
├── generated/
│   ├── discovered-flow.json← All TCs from last discovery
│   └── modules.json        ← Module list for rerun picker
├── templates/xpedite/
├── xpedite-output/
├── logs/
└── reports/
```

## Demo (local test)

Use the built-in demo app:

```json
{
  "url": "http://127.0.0.1:8765/index.html",
  "username": "admin_user",
  "password": "Pass@123",
  "app_name": "SMART BANK Demo"
}
```

## Browser Step Display

During automation, each step is shown live at the bottom of the browser.

Adjust speed in `config/selenium.json`:
```json
"step_display_delay_ms": 900
```

## Xpedite Export

After a run, artifacts are in **`xpedite-output/`**.

To re-export without Selenium: **`EXPORT-XPEDITE.bat`** or RUN.bat option **4**.

## First-Time Setup

```
SETUP.bat
```
Requires Google Chrome.
