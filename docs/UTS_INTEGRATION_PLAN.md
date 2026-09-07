# Bringing the UTS engine into Test by Token

> **Status: PLAN, nothing implemented.** Written 17 Aug 2026 after a full read of
> both codebases. This document supersedes the "Decision gate" section of
> [`bug_fixes.md`](bug_fixes.md) — the owner has now cemented **Model 2,
> hosted container**, and specifically *one container per user*. Every B-item in
> that backlog is therefore unblocked.

Three things are being asked for:

1. Make the **UTS engine** the thing that runs tests, from the get-go, instead of
   an AI writing a Playwright script per request.
2. Host it as a **separate mini server per user**.
3. Add an **in-app browser** so a user can complete a login that needs more than
   username + password — CAPTCHA, OTP, 2FA, SSO.

They are not three independent features. Finding **F5** below is why: #3 is the
thing that makes #1 legal under this product's own rules.

---

## Part 0 — What the review found

### F1. "The UTS worker" is the entire UTS platform

`UTS testing/uts-platform/` is 1,328 files: the Flask web app, RBAC across six
roles, 13 templates, the automation engine, the API farm, ALM/Xpedite exporters
*and* the worker agent. The UTS README says this outright — the server builds
`worker-package.zip` by zipping the whole repo minus secrets.

So the integration question is not "how do we copy the worker across." It is
**"which half of UTS do we keep."** Test by Token already has a control plane
(`backend/app.py`) and the owner explicitly likes its front end. Running two
control planes — FastAPI and Flask, two user models, two auth schemes, two
databases — would be the single worst outcome available.

### F2. The half worth keeping is `dynamic/` + `automation/` + `report_generator.py`

`dynamic/discovery.py:997 discover_application()` navigates the target, detects
and drives the login form (including Xpedite-style role/language dropdowns via
`dynamic/login_helpers.py`), then crawls modules, pages and elements. The
**offline, rule-based** planner turns that map into scenarios —
`UTS_AI_PROVIDER=offline` is the default and **no external AI service is called**.
`dynamic/automation_runner.py run_all_automation()` then replays them in Selenium.

That is exactly the capability the owner is asking for: *a real test suite,
generated and executed, without an AI writing a script per request.* Everything
else in UTS is control plane that Test by Token duplicates.

### F3. Step-level results already exist — they are simply never uploaded

This is the highest-leverage finding in the review.

- `automation/base.py:22 StepResult` carries `step_no, action, object_name,
  input_value, status, message, duration_ms, timestamp`.
- `report_generator.py:264` already **writes** `reports/e2e-results-<ts>.json`
  containing every `TestResult` and its `steps[]`.
- `worker/agent.py:57 _collect_artifacts()` uploads **four** things:
  `modules.json`, `discovered-flow.json`, `page-map.json`,
  `latest-e2e-report.html`. The results JSON is not one of them.

This single omission is the root cause of two bugs the UTS README lists
separately — "`ExecutionStep` is never written" and "pass/fail counts for local
runs are approximate" (`webapp/uts_service.py:621` globs for a file the worker
never sends). Adding one artifact fixes both **and** hands Test by Token's proof
screen the exact per-step data it renders. Cheapest win in the whole project.

### F4. `run_step()` is the single choke point for every step in the engine

`automation/base.py run_step()` wraps *every* action of *every* generated test
case. It already has a progress hook — `ExecutionLogger.on_progress` — and
already calls into the step overlay. Instrumenting that one function with a
per-step screenshot and a progress emit gives:

- per-step screenshots for the proof screen (today screenshots are failure-only,
  `automation/selenium_session.py screenshot_on_failure()`), and
- live step streaming, which is README build task 3 / `bug_fixes.md` **B1**.

One small edit, not a rewrite.

### F5. UTS as-is breaks Test by Token's central trust claim

`webapp/models.py Project` stores `app_username` and `app_password` as **plaintext
columns**. `webapp/worker_service.py enqueue_job()` copies both into the job
payload JSON, which is then served over HTTP to the agent. `dynamic/discovery.py`
types the password into the page.

Test by Token's hard rule, stated in the README and `docs/CREDENTIALS.md`:
*"Never accept login credentials in plaintext. No password field."*

These are irreconcilable. Adopting UTS's login model as-is would trade away the
product's whole trust posture. **The in-app browser is the resolution, not an
enhancement**: the user authenticates in a browser we render but never key-log,
and we retain only the resulting *session* — never the password. Ask #3 must ship
with ask #1, not after it.

### F6. The vendored copy carries real client data

`generated/` (76 BDD features), `alm-output/`, `xpedite-output/` (63 folders) and
`reports/` hold module names, test cases and exports from a live client app.
`frontend/index.html:246` also hardcodes that client's URL as the default —
already logged as **C4** in `bug_fixes.md`. All of it must be stripped before the
engine goes anywhere public.

### F7. Keep the poll-based worker protocol even though our containers don't need it

The agent never accepts inbound connections; it polls `heartbeat` and `next-job`
every 3s. In a container we control that indirection is unnecessary. Keep it
anyway: it makes *"run this on the customer's own machine"* a drop-in later,
which is what the roadmap's Rung 2–4 access ladder and enterprise handoff will
want. Same code path, two deployment targets. The cost is ~3s dispatch latency.

### F8. The decision gate is now closed

`bug_fixes.md` holds 11 items pending "API link vs. hosted container." Ask #2
cements **hosted container, one per user**. B1–B6 and the container-dependent
parts of A3, A6 and A7 are unblocked as of this document.

---

## Part 1 — Target architecture

Three tiers.

**1. Control plane — Test by Token (FastAPI + the homepage).**
Identity, projects, job queue, proofs, artifact storage, billing, guardrails.
One shared service, and the **only durable store**. The proof record lives here,
never in a container that gets destroyed.

**2. Workspace — one container per user.**
UTS engine + Chrome + chromedriver + Xvfb + x11vnc + noVNC + the worker agent.
Ephemeral compute and working state; uploads anything worth keeping.

**3. Engine — behind an interface, two adapters.**
- `PlaywrightEngine` — today's `backend/runner.py`. Seven fixed read-only checks,
  ~4 seconds, no container needed.
- `UtsEngine` — the trimmed UTS core. Deep crawl, generated suite, authenticated
  journeys, minutes not seconds.

Keeping both is deliberate and it is what `bug_fixes.md` **B2** was designed for.
See the open decision in Part 3 about which one serves the anonymous front page.

### Repo layout after the move

```
backend/          control plane (FastAPI)
  engines/        base.py · playwright_engine.py · uts_engine.py
  workspaces/     provisioner · registry · proxy
engine/           trimmed UTS core
frontend/         homepage (unchanged design) + workspace & login views
infra/            Dockerfile.workspace · compose
```

**Keep from `uts-platform/`:** `dynamic/`, `automation/`, `worker/`, `config/`,
`report_generator.py`, `run_automation_only.py`, `selenium_script_generator.py`.

**Drop:** `webapp/` (Flask control plane, RBAC, templates, admin), `api_farm/`,
`alm/`, `xpedite/`, all `generated/` · `*-output/` · `reports/` content, the
`_*.py` scratch scripts, the `.bat` installers and the portable-runtime path.

**Rebuild in FastAPI:** the six worker endpoints — `register`, `heartbeat`,
`next-job`, `progress`, `status`, `complete`. About 300 lines against a contract
that is already proven working (`webapp/worker_routes.py` is the reference).

Keep `UTS testing/` as the pristine vendor drop until the trim is verified end to
end, then delete it.

---

## Part 2 — Phases

### Phase A — Engine adapter, no containers yet · ~1–1.5 weeks

*Goal: Test by Token runs a UTS test on one machine and renders it in the
existing proof screen.*

| # | Task | Notes |
|---|---|---|
| A1 | Trim the vendor drop into `engine/` | Strip client data (**F6**) |
| A2 | Engine interface + wrap `runner.py` as adapter #1 | `bug_fixes.md` **B2**; prove zero behaviour change on the homepage |
| A3 | Async job model: `POST /runs` → id, `GET /runs/{id}/events` (SSE) | **B1** / README task 3; unblocks everything downstream |
| A4 | Result contract v1: UTS `e2e-results-*.json` → proof shape | **B4**; add `e2e_results` to `_collect_artifacts()` (**F3**) |
| A5 | Instrument `run_step()`: per-step screenshot + progress emit | **F4** — one function, whole engine instrumented |
| A6 | Worker protocol in FastAPI; run the agent locally against it | **F7** |
| A7 | Fix `bug_fixes.md` **A1** (XSS) and **A2** (run-ID collisions) | **Mandatory here, not later** — see below |

A7 is not optional housekeeping at this stage. The proof screen builds HTML with
`innerHTML` from `s.detail`. Today that string comes from seven fixed checks.
After A4 it carries crawled page titles, element labels and error messages from
the tested site — far more attacker-controlled text through the same hole.

**Exit:** paste a URL → UTS crawls → suite generates → steps stream live → proof
screen shows steps, screenshots and hash.

### Phase B — Per-user workspace containers · ~1.5–2 weeks

| # | Task | Notes |
|---|---|---|
| B1 | `Dockerfile.workspace` | Also fixes **A6** — we own the sandbox, so `--no-sandbox` goes |
| B2 | Provisioner + registry: create on demand, idle-stop, destroy, per-user quota | See sizing below |
| B3 | Token-authenticated reverse proxy; workspaces never publicly exposed | |
| B4 | Artifacts flow container → control-plane storage | `bug_fixes.md` **B3** |
| B5 | Free = ephemeral per run; paid = persistent workspace | Persistence is what makes the discovery cache and session bundles worth having |

**Sizing, stated plainly:** headful Chrome needs roughly 1–2 GB per live
workspace. A 16 GB host supports about **8–12 concurrent users**. This needs to
be modelled before test-token pricing is set.

**Exit:** two users run simultaneously, fully isolated, containers reaped on idle.

### Phase C — In-app browser and interactive login · ~1.5–2 weeks · the headline feature

| # | Task | Notes |
|---|---|---|
| C1 | `LOGIN_HANDOFF` state: navigate, then stop and emit `awaiting_login` | One state machine, two presentations |
| C2 | noVNC pane in the UI; single-use short-TTL token over WSS; "I'm signed in — continue" | |
| C3 | **Session capture, not credential capture** | See below |
| C4 | Session replay + validity probe | |
| C5 | Blackout rules during the handoff window | |
| C6 | Remove UTS's plaintext credential path | Resolves **F5** |

**C1 — two presentations, one mechanism.** The engine's behaviour is identical;
only the UI differs:
- hosted → embedded noVNC pane inside Test by Token
- local (dev, and later on-prem/enterprise) → *"finish the login in the Chrome
  window that just opened on your PC"*

The local mode is worth building first: it is nearly free, because UTS already
opens Chrome on the user's own machine. It de-risks the whole phase before any
container work is needed.

**C3 — what we capture.** On "continue": all cookies via CDP
`Network.getAllCookies` (**not** `driver.get_cookies()`, which only returns the
current domain — SSO flows span several), `localStorage` and `sessionStorage` per
origin, and the post-login URL. Stored as an encrypted session bundle with a TTL.
The password is never typed into anything we own, never transmitted to us, and
never stored.

**C4 — replay.** New run → inject cookies via CDP `Network.setCookies`, restore
storage, navigate, run a *"session still valid"* probe as step 1. If invalid,
re-prompt the in-app browser rather than failing the suite.

**C5 — blackout.** No screenshots, no DOM capture, no video while the user is
typing. The trace starts *after* authentication completes. Password fields stay
masked permanently.

**Why noVNC and not CDP screencast.** CDP `Page.startScreencast` is lighter and
prettier, and it is what a polished v2 should use. But MFA and SSO flows
routinely open popups and native dialogs, and screencast is per-target — every
popup becomes a new target to detect, attach to and route input for. noVNC shows
the whole session, so popups, IME and file pickers just work. Ship noVNC, optimise
later.

**Exit:** a user picks a site behind MFA, logs in inside the app, we never see the
password, the generated suite runs authenticated, and the proof shows the
authenticated journey.

### Phase D — Hardening before anything public

Now unblocked by the container decision: **A3** (egress controls at the container
network layer — far stronger than today's string check), **A4** rate limiting,
**A7** server-side signed proofs, **B6** token metering reconciled across two
engines, **C7** CORS. Plus the real vault (roadmap Phase 4) for scheduled and CI
runs, where no human is present to re-establish an expired session.

**Total: roughly 5–7 weeks for A + B + C.**

---

## Part 3 — Decisions needed from the owner

1. **Which engine serves the anonymous front page?** The ask is "UTS from the get
   go." The tension: the Playwright path returns a proof in ~4 seconds with no
   container; a UTS crawl takes minutes and needs a container *per anonymous
   visitor*. **Recommendation:** honour the ask by running UTS in a bounded
   "quick scan" profile for anonymous visitors (`list_modules_only` mode already
   exists, target 30–60s), and the full crawl once signed in. If that still feels
   slow on the landing page, keep Playwright for the anonymous hit only.
2. **Container host** — one Docker host to start, or straight to Fly.io machines
   / Kubernetes? Affects B2 materially.
3. **What happens to the VPS?** Retire, keep, or make it the enterprise lane. The
   UTS README flags nine accounts and projects owned by eight of them — not
   purely this project's call.
4. **Data** — blank workspaces, or migrate `web-data/uts_platform.db` (18
   projects, 269 modules, 26 executions) off the VPS into the new model?
5. **Session TTL and re-auth policy** for scheduled runs — this is what decides
   how soon the real vault is needed.

---

## Part 4 — Risks

| # | Risk | Handling |
|---|---|---|
| R1 | Two browser stacks (Selenium + Playwright), two driver-management paths | Acceptable while they stay in separate processes/containers. Never mix them in one process. |
| R2 | **Crawl quality.** The UTS README records project 18 with most of its 25 modules at `0 pages · 0 flows` — the generated suite is only as good as the crawl | Needs a quality gate and an honest "we found nothing here" state, or the proof screen renders an empty suite and reads as broken |
| R3 | The noVNC pane is a remote-control channel into a container with internet egress | Single-use scoped tokens, egress limits, destroy on session end — mandatory, not optional |
| R4 | Session bundles are bearer credentials in their own right | Encrypt at rest, TTL, bind to workspace, audit every access — treat exactly as the vault would be |
| R5 | Cost: every authenticated test is a container running Chrome | Model it before pricing test-tokens (see Phase B sizing) |
