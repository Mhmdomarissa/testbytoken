# Handover — Test by Token

Everything you need to pick this repository up. Read this file top to bottom
once, then follow the "reading order" in section 6 for whichever half you are
working on.

---

## 1. What this repository actually is

**Two related projects living in one repo.** They are converging, but they are
not the same codebase, and it matters which one you are touching.

| | **Test by Token** (the product) | **UTS** (the engine being adopted) |
|---|---|---|
| What | Testing-as-a-Service demo: paste a URL, describe a test in plain English, a real browser runs it and returns an auditable proof | An existing Flask + Selenium test-automation platform the company already runs on a VPS |
| Lives in | `services/api/`, `services/web/` | `services/engine/` (trimmed engine); `reference/uts-platform/` (vendored copy) |
| Stack | Python + FastAPI + Playwright, plain HTML/CSS/JS front end | Python + Selenium |
| Read first | [`README.md`](../README.md) | [`reference/README.md`](../reference/README.md) |

The current work — and the branch you will check out — is **joining them**:
making the UTS engine the thing that actually runs customer tests, one warm
engine workspace per user, with an interactive login so a customer can clear
MFA/SSO without ever handing over a password.

That plan is [`docs/UTS_INTEGRATION_PLAN.md`](UTS_INTEGRATION_PLAN.md).
**Read it before writing any code** — it explains which half of UTS is being
kept and, more importantly, which half is deliberately being thrown away.

---

## 2. Where the work is

```
branch: feat/uts-engine-integration      <- everything is here, this is your branch
branch: master                           <- older; fully contained in the branch above
```

`master` has **zero** commits that are not already in
`feat/uts-engine-integration`. Do not try to merge or reconcile them — just work
on the feature branch.

The repo was reorganized into `services/` (see section 3) on the
`refactor/service-split` branch. Always confirm the real current branch with
`git status` rather than trusting this section — it is exactly the kind of
thing that goes stale.

---

## 3. Repo map

```
README.md                     The product brief: what is built, hard rules, tech choices
Makefile                       Every run command lives here
.env.example                    Every env var either service reads, with safe defaults

docs/
  HANDOVER.md                  You are here
  bug_fixes.md                 Full code review — every known bug + how to fix it (43 KB)
  UTS_INTEGRATION_PLAN.md      THE current design doc. Start here.
  TEST_ENVIRONMENT.md          How to run the UTS console + every wired endpoint
  ROADMAP.md                   Product ladder through Rung 4
  SETUP.md                     Original setup notes — pre-dates the services/ split, stale (see caveat in section 5)
  CREDENTIALS.md               Why there is no password field. Read before touching auth.
  sample_result.json           Shape of an auditable result

services/
  api/                         Control plane — FastAPI + Playwright, own .venv
    requirements.txt
    tbt_api/
      main.py                    FastAPI app, middleware, router wiring, /health, /shots mount
      config.py                   Env vars, is_allowed_target(), normalize_target()
      schemas.py                   Pydantic models for /plan and /run
      routes/
        plan.py                     POST /plan
        run.py                       POST /run
        uts.py                       The UTS engine API (/uts/*) — was backend/uts_routes.py
      engines/
        base.py                     Abstract engine interface (TestEngine/EngineRun)
        playwright_runner.py         Original Playwright engine (proven, do not rewrite) — was backend/runner.py
        uts_workspace.py             Per-user engine workspace lifecycle — was backend/workspaces.py
    tests/                        pytest — config.py's target guardrail, main.py's routes

  engine/                       UTS engine — Selenium, own .venv (permanently separate from api/.venv)
    requirements.txt
    uts_engine/
      host.py                     Per-user engine host process — was engine_host.py
      cli.py                       Two-cycle scan/run CLI — was run_automation_only.py
      discovery/                    Crawls the target app, drives the login form — was dynamic/, minus AI planning
        discovery.py                  Crawls the target app, drives the login form
        automation_runner.py           Replays discovered scenarios in Selenium
      planning/                     ai_brain.py, ai_pipeline.py, page_intelligence.py — was also in dynamic/
      automation/                   Selenium step execution (unchanged internally)
      exporters/                    alm/, xpedite/, report_generator.py, selenium_script_generator.py, excel_writer.py
    config/                       JSON config (app-input.json, selenium.json, ...)
    demo-app/                    Bundled demo fixture
    tests/                        pytest — package import sanity, a pure-function check

  web/                          Frontend — plain HTML/CSS/JS
    index.html                    Customer homepage with the live hero test launcher
    console.html                   The UTS console (deliberately plain — shape, not styling) — was uts-console.html

reference/
  README.md                     UTS teardown: architecture, all known bugs, verified run log — was "UTS testing/README.md"
  uts-platform/                 Vendored full UTS platform (1,328 files) — reference copy, untouched
  UTS-Connect-JackTest.bat        The broken installer, kept as evidence. Do NOT "fix" it.
  UTS-Connect-JackTest-FIXED.bat  The corrected installer, verified working.

design_handoff_adr_website/   Approved design language the homepage follows
```

---

## 4. What is NOT in git (and how to get it back)

Nothing here is lost — it is all either regenerable or deliberately excluded.

| Missing | Why | How to get it |
|---|---|---|
| `services/api/.venv/`, `services/engine/.venv/` | Environment, not source | `make setup-api setup-engine` |
| `workspaces/`, `services/api/shots/`, `services/engine/generated/`, `services/engine/reports/`, `services/engine/logs/` | Run artifacts, regenerated every run | Just run something |
| `reference/uts-platform/runtime/` | Portable Python 3.12, 96 MB / 4,009 files | Re-run the FIXED connector, or skip it and use a normal venv |
| `reference/uts-platform/web-data/` | Contains a live Bearer token | Deliberately excluded — do not ask for it, mint your own |
| The UTS production database | 18 projects / 269 modules live on the VPS | Only by copying `web-data/uts_platform.db` off the VPS. A local instance starts empty, which is fine for development. |

---

## 5. Getting it running

**Prerequisites:** Python 3.11 or newer (3.13 is what this was last run on),
Google Chrome, and Git. On a machine where Homebrew Python 3.12 has a broken
pyexpat/libexpat link, the Makefile already sets
`DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib` for every target.

### The product (Test by Token)

```bash
make setup-api
```

Then two processes — both are pre-defined in `.claude/launch.json`:

```bash
make api
```

```bash
make web
```

Open:

- **http://localhost:5500** — the customer homepage (Playwright checks)
- **http://localhost:5500/console.html** — the UTS engine console

> **Caveat:** `docs/SETUP.md` says port **8000** and still describes the
> pre-split `backend/` layout. That is stale — the current port is **8001**,
> as in `.claude/launch.json` and `docs/TEST_ENVIRONMENT.md`. Trust 8001, and
> trust this file and the Makefile over `docs/SETUP.md`.

**No API key is needed to start.** If `ANTHROPIC_API_KEY` is unset, the planner
falls back to a built-in keyword planner and the free-text box still works.

**`TAAS_LOCAL_DEMO` defaults to `1`**, which lifts the target guardrails so you
can test localhost and local files from your own laptop. It **must** be `0` on
anything other people can reach.

### The engine on its own

```bash
make setup-engine
make engine-scan   # Cycle 1: login + crawl + list modules
make engine-run    # Cycle 2: generate test cases + execute them
```

### The vendored UTS platform (reference / fixing bugs at source)

`reference/uts-platform/` ships `RUN-WEB.bat` and `run-web.sh`, which build a
venv and start it against local SQLite. See the "How to run it locally"
section of [`reference/README.md`](../reference/README.md) — including the
one known blocker (`run_web.py` is missing a `sys.path.insert`, with the fix
written out).

---

## 6. Reading order for your first day

1. `README.md` — what the product is, and the **hard rules** (they are real: no
   plaintext credentials, read-only checks, one disposable browser context per run)
2. `docs/UTS_INTEGRATION_PLAN.md` — the current design and its findings F1–F5
3. `docs/TEST_ENVIRONMENT.md` — run the console and click through it once
4. `reference/README.md` — how UTS really works, and everything wrong with it
5. `docs/bug_fixes.md` — the backlog, in implementation order

---

## 7. Things to know before you touch anything

- **Never accept login credentials in plaintext.** No password field. This is
  the product's core promise, not a preference. `docs/CREDENTIALS.md` explains
  the intended vault pattern and what not to build yet.
- **`playwright_runner.py` is proven working.** Wrap it, do not rewrite it.
- **Keep the engine swappable.** Do not deepen the API's direct coupling to any
  one engine — route through `services/api/tbt_api/engines/base.py`.
- **`services/api/` and `services/engine/` keep permanently separate
  virtualenvs.** Selenium and Playwright must never share a process.
- **The two `.bat` files in `reference/` have pinned line endings** via
  `.gitattributes`. The broken one is LF **on purpose** — it is the evidence for
  installer defect #1. Do not normalise them.
- **Test cases are only as good as the crawl.** Modules that crawl to
  `0 pages · 0 flows` produce nothing. That is expected behaviour, not a bug.

---

## 8. Credential hygiene — action required

Two files in the vendored UTS platform contain **hardcoded passwords**, and they
are in the committed history:

- `reference/uts-platform/_create_jacktest.py` — the live `JackTest` account password
- `reference/uts-platform/run_xpedite_export.py` — a default test password

Treat the `JackTest` credential as **compromised and due for rotation**, and do
not reuse it anywhere. Do not push this repository to any public host.

---

## 9. Open questions for the owner

Carried over from `reference/README.md` — still unanswered:

1. Is the VPS still shared with other active users? Nine accounts exist, so
   retiring it is not a solo decision.
2. Is a local instance meant to replace the VPS, or run alongside it?
3. Does anyone rely on the ALM / Xpedite exports? They currently only ever exist
   on whichever machine ran the test.
