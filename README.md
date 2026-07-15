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

- `backend/runner.py` — the test engine. Real Playwright/Chromium. Produces the
  full auditable trace + token cost. **Tested live against a real single-page app
  and passed 5/5.** Do not rewrite this; wrap it.
- `backend/app.py` — FastAPI wrapper. `/plan` (LLM maps text→checks), `/run`
  (executes the test), `/health`. Includes the free-tier safety guardrails.
- `frontend/index.html` — single-file clickable demo of all four journey steps.
  Talks to the backend over fetch.

## Your build tasks, in order

1. **Get the backend running locally.** See `docs/SETUP.md`. Confirm `/health`,
   then `/run` against a public URL returns a PASS.
2. **Serve screenshots.** Right now `runner.py` writes PNGs to a `shots/` dir but
   the frontend can't see them. Add a static route (e.g. mount `/shots`) OR change
   the runner to return the screenshot as base64 in the JSON. Wire the frontend
   `#shot` image to display it. (Marked as a TODO in `frontend/index.html`.)
3. **Stream the run live** (nice-to-have). Right now `/run` is one blocking call.
   Upgrade to server-sent events / websocket so steps tick green in real time —
   that's what makes step 3 feel alive. Ship the blocking version first.
4. **Add the signup wall** after the proof screen. Stub it — email capture only.
5. **Stub the credentials vault UI.** Do NOT build real crypto yet. Read
   `docs/CREDENTIALS.md` — it explains the pattern and what NOT to do.
6. **Deploy.** A single container running the backend + serving the frontend is
   fine for the demo. See `docs/SETUP.md` for the deploy note.

## Hard rules (do not break these)

- **Never accept login credentials in plaintext** over the API or in the frontend.
  No password field in the demo. Credential handling is a separate, later, vaulted
  feature. See `docs/CREDENTIALS.md`.
- **Keep the free-tier target guardrails** in `app.py` (`is_allowed_target`). They
  block internal/private hosts so the demo can't be used to attack infrastructure.
- **Read-only checks only** on the free path. No form submissions, no writes.
- **One disposable browser context per run.** Never share state between runs.

## Architecture context (the bigger picture)

This demo is Phase 1 of a larger platform (enterprise + self-serve lanes, token
billing, a swappable engine that can route to legacy-system test tools). You don't
need that now. The full architecture lives in the separate architecture doc the
owner has. Build the demo so the engine (`runner.py`) stays swappable — the API
shouldn't care what runs inside the container.

**Planned engine direction (July 2026):** test execution will route to the
**UTS Global Test Magic** system, either over an API link or as an instance we
host in a container — that decision is not yet cemented. Until it is, treat the
local Playwright engine as adapter #1 of a swappable engine layer, and do not
deepen the API's direct coupling to `runner.py`.

## Known issues & remediation plan — READ BEFORE BUILDING FURTHER

A full code review (July 2026) produced [`bug_fixes.md`](bug_fixes.md): every
known bug, security hole, and architecture change, each with detailed fix
instructions, verification steps, and a flag for whether it depends on the UTS
integration decision. Highlights:

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
