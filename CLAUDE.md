# CLAUDE.md — Test by Token / UTS

Instructions for Claude (Claude Code / Cowork) working in this repository.
Read this file first, every session. This is a **company codebase**, not a
personal project — treat it with the discretion that implies: no secrets in
commits, no speculative pushes to shared branches, no destructive commands
without confirmation, and no exposing client-identifying details in generated
docs, PRs, commit messages, or conversation summaries outside this repo.

---

## 1. Orientation — do this before writing any code

1. Read `docs/HANDOVER.md` top to bottom. It is the actual entry point for this
   repo and stays more current than this file for day-to-day state (branch,
   ports, what's done).
2. Read `docs/UTS_INTEGRATION_PLAN.md` if the task touches `services/engine/`,
   `services/api/tbt_api/routes/uts.py`, `services/api/tbt_api/engines/uts_workspace.py`,
   or anything under `reference/uts-platform/`.
3. Check `docs/bug_fixes.md` for the area you're about to touch before changing
   it — it's a standing code-review backlog with known bugs, severities, and
   whether each is blocked on the UTS hosting decision. Don't reintroduce a
   bug that's already documented there, and don't silently "fix" something
   marked as blocked without flagging it.
4. Run `git branch -a` and `git status` to see the real current branch —
   don't trust a branch name from any doc without checking; docs here have
   already gone stale on this once (see the port caveat below).

## 2. What this repo actually is

Two related codebases converging into one product, now split into
`services/` as two independently runnable services:

| | **Test by Token** (the product) | **UTS** (the engine being adopted) |
|---|---|---|
| What | TaaS demo: paste a URL, describe a test in plain English, a real browser runs it and returns an auditable proof | Existing Flask + Selenium test-automation platform the company already runs on a VPS |
| Lives in | `services/api/`, `services/web/` | `services/engine/` (trimmed engine); `reference/uts-platform/` (vendored reference copy — see §7.4) |
| Stack | Python + FastAPI + Playwright, plain HTML/CSS/JS frontend | Python + Selenium |

Current work is **joining them**: UTS becomes the engine that runs customer
tests, one warm engine workspace per user, with interactive login so a
customer clears MFA/SSO without ever handing over a password.

## 3. Repo map (condensed — see docs/HANDOVER.md §3 for the full version)

```
README.md            Product brief, hard rules, tech choices
Makefile              Every run command lives here — setup-api, setup-engine, api, web, engine-scan, engine-run, test, clean
.env.example           Every env var read by either service, with safe defaults
docs/
  HANDOVER.md              Current entry point — reading order, repo map, open questions
  bug_fixes.md             Full code-review backlog (43KB) — bug IDs, severity, fix, blocked-on-UTS?
  UTS_INTEGRATION_PLAN.md   Current design doc for the engine merge
  TEST_ENVIRONMENT.md       How to run the UTS console, every wired endpoint
  ROADMAP.md                Product phases (Rung 1–4) — check before scoping new features
  CREDENTIALS.md            The vault pattern — read before touching any auth/credential code
services/
  api/                 Control plane — FastAPI + Playwright, own .venv
    tbt_api/
      main.py             FastAPI app, middleware, router wiring, /health, /shots mount
      config.py            Env vars, is_allowed_target(), normalize_target()
      schemas.py            Pydantic models for /plan and /run
      routes/
        plan.py              POST /plan
        run.py                POST /run
        uts.py                UTS engine API (/uts/*)
      engines/
        base.py              Abstract engine interface (TestEngine/EngineRun)
        playwright_runner.py  Original Playwright engine — PROVEN WORKING, wrap it, do not rewrite
        uts_workspace.py      Per-user engine workspace lifecycle
  engine/               UTS engine — Selenium, own .venv (permanently separate from api/.venv)
    uts_engine/
      host.py              Per-user engine host process (was engine_host.py)
      cli.py                Two-cycle scan/run CLI (was run_automation_only.py)
      discovery/             Crawl, login, module detection (was dynamic/, minus AI planning)
      planning/               AI-assisted planning (ai_brain.py, ai_pipeline.py, page_intelligence.py)
      automation/              Selenium step execution
      exporters/                ALM, Xpedite, report and Selenium-script generation
  web/                  Frontend — stays plain HTML/CSS/JS
    index.html            Customer homepage with the live hero test launcher
    console.html            UTS console (plain on purpose — shape, not styling)
reference/uts-platform/   Vendored full UTS platform — reference copy, 1,300+ files (was "UTS testing/uts-platform/")
```

## 4. Running it locally

Everything is one `make` command away from the repo root:

```bash
make setup-api      # creates services/api/.venv, installs requirements, playwright install chromium
make setup-engine   # creates services/engine/.venv, installs requirements
make api            # uvicorn on port 8001 — NOT 8000, docs/SETUP.md is stale, trust 8001
make web            # python -m http.server 5500 --directory services/web
```

Open `http://localhost:5500` (homepage) or `http://localhost:5500/console.html`
(UTS console). `make api` and `make web` are also pre-defined in
`.claude/launch.json`.

**`services/api/` and `services/engine/` keep permanently separate virtualenvs.**
Selenium (engine) and Playwright (api) must never share a process — see
`services/api/tbt_api/engines/uts_workspace.py` and the Makefile's own comment.
Never run one service's code from inside the other's `.venv`.

No `ANTHROPIC_API_KEY` is required to start — the `/plan` endpoint falls back
to a built-in keyword planner. See `.env.example` for every other env var
either service reads.

## 5. Non-negotiable rules — do not break these, ever

These come straight from `README.md` / `docs/HANDOVER.md` and are product
guarantees, not style preferences:

- **Never accept or transmit login credentials in plaintext.** No password
  field anywhere in this product's own UI/API. Any credential-adjacent
  feature must follow the vault pattern in `docs/CREDENTIALS.md` (encrypted
  at rest, write-only through the UI, injected only inside a disposable
  container at run time, never echoed back, never logged).
- **Read-only checks only on the free tier.** No form submissions, no writes,
  from anything reachable by the public.
- **One disposable browser context per run.** Never share state between runs.
- **`TAAS_LOCAL_DEMO` must be `0` on anything reachable by other people.**
  It's `1` by default for local dev and lifts the SSRF/target guardrail
  (`is_allowed_target()` in `services/api/tbt_api/config.py`) — that bypass
  is for a single laptop only.
- **Do not rewrite `services/api/tbt_api/engines/playwright_runner.py`.** It's
  proven working; wrap it.
- **Keep the engine swappable.** Don't deepen `main.py`'s direct coupling to
  any one engine — route through `services/api/tbt_api/engines/base.py`
  instead of importing `playwright_runner.py` or `uts_workspace.py` directly
  outside their own route module. The hosting model for UTS (API link vs.
  hosted container) is not yet decided (`docs/bug_fixes.md`, "Decision gate").
- **The two services keep separate virtualenvs, permanently** — see §4.
- Production runs (per `docs/ROADMAP.md`) are **read-only after login** —
  never add a write-path test that could run against a customer's production
  environment.

## 6. Company / confidentiality rules

- **This is proprietary company code.** Never suggest or execute anything
  that would make the repository or its history more public than it already
  is (force-pushing to a public remote, publishing a gist/snippet of real
  code or credentials, etc.) without being explicitly asked.
- **`reference/uts-platform/_create_jacktest.py` and `run_xpedite_export.py`
  contain hardcoded passwords already committed to history.** Treat the
  `JackTest` credential as compromised. Never reuse it anywhere, never
  reference its value in output, and flag (don't silently fix) any request
  that would touch these files.
- Don't invent or assume client/company names, URLs, or account details in
  code comments, tests, or docs — `docs/bug_fixes.md` item **C4** already
  flags a real client URL hardcoded in the demo; don't add more of that
  pattern, and point it out if you encounter it again.
- Don't commit `.env`, anything under `workspaces/`, or run artifacts —
  `.gitignore` already covers this; don't fight it.
- If a task would remove or weaken a guardrail in §5, stop and ask instead of
  proceeding, even if the immediate feature request seems to require it.

## 7. How to work here — as a senior engineer would

**7.1 Before implementing anything**
- Check `docs/bug_fixes.md` for the area — don't build on top of a
  documented bug without at least flagging it.
- Check `docs/ROADMAP.md` to see which phase (Rung 1–4) the feature belongs
  to; don't build Phase 3/4 capability (GitHub App, real vault crypto) into
  what's still a Phase 0/1 demo path unless asked.
- If the change touches the engine boundary (`playwright_runner.py`,
  `routes/uts.py`, `uts_workspace.py`, anything under `services/engine/`),
  re-read `docs/UTS_INTEGRATION_PLAN.md` first — the UTS hosting decision is
  still open, and speculative architecture there gets thrown away.

**7.2 Searching the codebase**
- `services/api/`, `services/web/`, `services/engine/` are the live product —
  search here first.
- `reference/uts-platform/` is a **vendored reference copy** (1,300+ files)
  of the platform already running on the company VPS. Treat it as read-mostly:
  only edit it when the task is explicitly "fix the bug at its source in UTS",
  per `docs/HANDOVER.md`. Don't refactor it opportunistically.
- The two `.bat` files at `reference/UTS-Connect-JackTest.bat` and
  `reference/UTS-Connect-JackTest-FIXED.bat` have intentionally pinned,
  mismatched line endings (`.gitattributes`) — one is deliberately broken as
  evidence of a documented installer bug. Never "normalize" or "fix" their
  line endings.

**7.3 Writing code**
- Match existing style: FastAPI + Pydantic models in `services/api/tbt_api/`,
  docstring-led modules (see the header comment style in `main.py`), type
  hints where the surrounding code already uses them.
- Small, reviewable diffs over sweeping rewrites. Explain trade-offs rather
  than picking silently when there's a real architectural choice (e.g.
  anything the UTS decision gate affects).
- No new frameworks, build tooling, or major dependencies without asking —
  README is explicit that the frontend stays plain HTML/CSS/JS "for the demo."

**7.4 Testing**
- `services/api/tests/` and `services/engine/tests/` hold a first real pytest
  suite for each service — run both with `make test`. They're still thin
  (`docs/bug_fixes.md` item **C8**); `services/engine/uts_engine/automation/test_*.py`
  are Selenium scenario scripts, not part of that pytest suite.
- When adding a new feature or fixing a bug, add or update a real test in the
  matching service's `tests/` dir — don't just eyeball it manually, even
  though the existing code often does.
- Manually verify against the running app when a fix touches `/plan`, `/run`,
  or `/uts/*` — hit `/health` first (`curl http://localhost:8001/health`),
  then the specific endpoint. See §4 for how to start the server.

**7.5 Build / deploy**
- Single container per service is fine for the demo stage: install deps +
  `playwright install --with-deps chromium` for `services/api/`, run
  uvicorn, serve `services/web/index.html`.
- Before anything deployed publicly: `TAAS_LOCAL_DEMO=0`, lock CORS down from
  `allow_origins=["*"]` (`docs/bug_fixes.md` **C7**), and confirm A1–A4 in
  `docs/bug_fixes.md` (XSS, run-ID collisions, guardrail hardening, rate
  limiting) are actually resolved — don't deploy publicly with those still open.

**7.6 Git discipline**
- Confirm the actual current branch before starting (`git status`) —
  don't assume from a doc.
- Never force-push, rewrite history, or delete branches without being asked.
- Ask before committing anything under `reference/uts-platform/generated`,
  `alm-output`, `xpedite-output`, `reports`, or `logs` even if `.gitignore`
  didn't catch a new variant of a run-artifact path — these have carried real
  client module/test-case names before and were stripped from history once.

## 8. Known landmines

- Port is **8001**, not 8000 — `docs/SETUP.md` is stale (it still describes
  the pre-split `backend/` layout too — trust this file and `docs/HANDOVER.md`
  over it).
- `playwright_runner.py` in `services/api/tbt_api/engines/` is the original
  Playwright engine; there's also `services/engine/uts_engine/` — don't
  confuse the two when asked to "fix the runner."
- This machine's Homebrew Python 3.12 needs
  `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib` for a broken pyexpat/libexpat
  link — the Makefile already sets this for every target; only relevant if
  you run a venv command by hand outside `make`.
- A module that crawls to "0 pages · 0 flows" is expected UTS behavior, not
  a bug to chase.
- `chat transfer.zip` is committed at repo root (`docs/bug_fixes.md` **C3**,
  flagged for removal) — don't add more binary/zip artifacts to git the same
  way.

## 9. When to stop and ask instead of guessing

- Any change that weakens a §5 guardrail.
- Anything touching the UTS hosting model (API vs. hosted container) — it's
  an open decision, not yours to make in a PR.
- The three open questions `docs/HANDOVER.md` already lists for the owner
  (VPS sharing, local-vs-VPS replacement, ALM/Xpedite export usage) — don't
  answer these by assumption in code.
- Any request that would touch, reference, or reuse the compromised
  `JackTest` credential.
