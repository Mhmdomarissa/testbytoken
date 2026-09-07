# Testing-as-a-Service — demo build (handover to Claude Code)

> **Read this first.** You are picking up a working proof-of-concept and turning it
> into a runnable demo app. The hard part — a real browser test that produces an
> auditable result — is already written and proven working. Your job is to wire it
> into a clean web app, not to reinvent the engine.

## What this product is (one paragraph)

A web platform where someone pastes a URL, says what they want tested in plain
English, and watches a **real browser** run the test and hand back an **auditable
proof**: every step, screenshots, pass/fail, a timestamp, a tamper-evident hash,
and a compute cost in "test-tokens". The whole pitch is *deterministic + auditable*
— the opposite of asking a general AI "does my login work?" and getting a guess.

## The customer touch journey (what the demo must show)

1. **Land** — paste a URL. No signup.
2. **Describe** — a "what would you like to test?" box, with quick-pick buttons
   (Page load, User login). Free text is mapped to checks by an LLM; quick picks
   map instantly with no LLM call.
3. **Watch it run** — the real browser executes; steps appear.
4. **The proof** — the auditable report. **This is the value moment.**

The signup wall comes **after** step 4, not before. Deliver value first.

## What's already done and PROVEN WORKING

- `services/api/tbt_api/engines/playwright_runner.py` — the test engine. Real
  Playwright/Chromium. Produces the full auditable trace + token cost.
  **Tested live against a real single-page app and passed 5/5.** Do not
  rewrite this; wrap it.
- `services/api/tbt_api/main.py` — FastAPI control plane, assembled from
  `config.py`, `schemas.py` and `routes/`. `/plan` (LLM maps text→checks),
  `/run` (executes the test), `/health`. Serves screenshots read-only at
  `/shots`. Free-tier safety guardrails included, with a local-demo bypass
  (see below).
- `services/web/index.html` — the full customer-facing homepage ("Proof — Testing
  as a Service"), built July 2026 in the approved design language
  (`design_handoff_adr_website/DESIGN_LANGUAGE.md`): nav, hero, stats bar,
  about split, service cards, four-step tiles, CTA band, footer. The hero
  embeds the live test launcher — all four journey steps work end to end,
  including the proof screen with screenshot and trace hash. Desktop-only for
  now; photos are Unsplash placeholders.

## Running it locally

Two processes, both one `make` command away from the repo root (or use
`.claude/launch.json`, which defines both):

```bash
make setup-api   # first time only — venv, requirements, playwright install chromium
make api         # the engine API, port 8001
make web         # the homepage, port 5500
```

Then open http://localhost:5500. The frontend expects the API at
`http://localhost:8001` (override with `window.API_BASE`). If the API
isn't running, the launcher says so and shows the start command.

**Local demo mode:** `TAAS_LOCAL_DEMO` (default `1`) lifts the target
guardrail so you can test anything from your own laptop — localhost, private
IPs, bare domains (auto-prefixed `https://`), even local HTML files
(`C:\path\to\page.html` is converted to a `file:///` URL). `/plan` drops the
HTTPS check for non-https targets so local runs aren't guaranteed a failed
step. **Set `TAAS_LOCAL_DEMO=0` before any public deployment** — that
re-enables `is_allowed_target()` and blocks `file://` targets.

**Free-text test requests (the "what would you like to test?" box):** the
planner turns plain English into concrete checks. If `ANTHROPIC_API_KEY` is set,
Claude maps the request; otherwise (or if that call fails) a built-in
**keyword planner** handles it, so the box works out of the box with no key.
Example: *"test all the buttons and make sure all the links work"* →
`page_load`, `links_work`, `buttons_present`.

**Supported checks** (`SUPPORTED_CHECKS` in `services/api/tbt_api/routes/plan.py`,
executed by `playwright_runner.py`): `page_load`, `title`, `https`,
`login_present`, `performance`, plus two content checks:
- `links_work` — collects every anchor on the rendered page and HTTP-checks each
  one (read-only HEAD/GET, capped at 25); fails if any return ≥ 400 or are
  unreachable.
- `buttons_present` — enumerates all `button` / button-role elements and confirms
  they render and are visible + enabled (clickable). It does **not** click them —
  clicking arbitrary buttons could submit forms or trigger writes, which the
  free tier forbids.

## Your build tasks, in order

1. ~~**Get the backend running locally.**~~ DONE — `/health` OK, `/run`
   returns PASS with trace hash + tokens.
2. ~~**Serve screenshots.**~~ DONE — mounted at `/shots`, `shot_url` added per
   step after hashing, rendered in the proof screen.
3. **Stream the run live** (nice-to-have). Right now `/run` is one blocking call.
   Upgrade to server-sent events / websocket so steps tick green in real time —
   that's what makes step 3 feel alive. (Designed in detail as B1 in
   `docs/bug_fixes.md` — build it in that shape.)
4. **Add the signup wall** after the proof screen. Stub it — email capture only.
5. **Stub the credentials vault UI.** Do NOT build real crypto yet. Read
   `docs/CREDENTIALS.md` — it explains the pattern and what NOT to do.
6. **Deploy.** A container per service (`services/api/`, `services/engine/`)
   is fine for the demo. See `docs/SETUP.md` for the deploy note (paths there
   pre-date the `services/` split — trust the Makefile for the real commands).

## Hard rules (do not break these)

- **Never accept login credentials in plaintext** over the API or in the frontend.
  No password field in the demo. Credential handling is a separate, later, vaulted
  feature. See `docs/CREDENTIALS.md`.
- **Keep the free-tier target guardrails** in `services/api/tbt_api/config.py`
  (`is_allowed_target`). They block internal/private hosts so the demo can't
  be used to attack infrastructure. The `TAAS_LOCAL_DEMO` bypass exists for
  single-laptop demos ONLY — it must be `0` on anything reachable by other
  people. (Guardrail hardening beyond the string check is A3 in
  `docs/bug_fixes.md`.)
- **Read-only checks only** on the free path. No form submissions, no writes.
- **One disposable browser context per run.** Never share state between runs.

## Architecture context (the bigger picture)

The product roadmap — access ladder through Rung 4, growth funnel to
enterprise handoff — is in [`docs/ROADMAP.md`](docs/ROADMAP.md).

This demo is Phase 1 of a larger platform (enterprise + self-serve lanes, token
billing, a swappable engine that can route to legacy-system test tools). You don't
need that now. The full architecture lives in the separate architecture doc the
owner has. Build the demo so the engine (`playwright_runner.py`) stays
swappable — the API shouldn't care what runs inside the container. Route
through `services/api/tbt_api/engines/base.py` rather than importing an
engine module directly outside its own route.

**Planned engine direction (July 2026):** test execution will route to the
**UTS Global Test Magic** system, either over an API link or as an instance we
host in a container — that decision is not yet cemented. Until it is, treat the
local Playwright engine as adapter #1 of a swappable engine layer, and do not
deepen the API's direct coupling to `playwright_runner.py`.

## Known issues & remediation plan — READ BEFORE BUILDING FURTHER

A full code review (July 2026) produced [`docs/bug_fixes.md`](docs/bug_fixes.md):
every known bug, security hole, and architecture change, each with detailed
fix instructions, verification steps, and a flag for whether it depends on
the UTS integration decision. Highlights:

- **Critical bugs** (XSS from tested sites, run-ID collisions, bypassable
  target guardrail, open endpoints with no rate limit) — documented with fixes,
  **not yet applied**.
- **Architecture items** (async job model, engine abstraction for the UTS
  adapter, artifact storage, persistence + versioned result contract, signed
  proofs) — designed but deliberately on hold until the UTS hosting model
  (API vs. container) is decided.

Implementation order and the UTS decision gate are spelled out at the top of
that document. Anything marked **UTS-independent** may be implemented at any
time; everything else waits.

## Tech choices (already made for you)

- Backend: Python + FastAPI + Playwright. Keep it.
- LLM: Anthropic Claude (`claude-sonnet-4-6`) via the `anthropic` SDK, key in env.
- Frontend: plain HTML/CSS/JS for the demo. If you want a framework later, fine,
  but don't add build complexity before the demo works end to end.
