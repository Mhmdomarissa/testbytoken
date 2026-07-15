# Bug fixes & architecture remediation plan

> **Status: DOCUMENTED, NOT IMPLEMENTED.**
> This document is the full remediation backlog from the July 2026 code review.
> Nothing here has been applied yet — implementation is deliberately on hold until
> the UTS Global Test Magic integration model is cemented (API link vs. hosting an
> instance in a container). See [Decision gate](#decision-gate-the-uts-global-test-magic-integration)
> for exactly which items that decision affects. Items marked **UTS-independent**
> are safe to implement at any time.

---

## Index and priority

| ID | Title | Severity | Blocked on UTS decision? |
|----|-------|----------|--------------------------|
| A1 | XSS from tested sites in the proof screen | **Critical** | No — UTS-independent |
| A2 | Run-ID collisions under concurrency | **Critical** | No — UTS-independent |
| A3 | Bypassable private-host guardrail (SSRF) | **Critical** | Partially (network-layer part) |
| A4 | No rate limiting — open LLM/compute drain | **High** | No — UTS-independent |
| A5 | Unhandled LLM failures return raw 500s | **High** | No — UTS-independent |
| A6 | Chromium runs with `--no-sandbox` | **High** | Partially (per-run container part) |
| A7 | "Tamper-evident" hash is not tamper-evident | **High** (core product claim) | Yes — depends on B1/B4 |
| B1 | Synchronous `/run` — needs an async job model | **Architecture** | Yes — design now, shape confirmed by UTS |
| B2 | No engine abstraction layer | **Architecture** | Yes — the UTS adapter plugs in here |
| B3 | Screenshots on local disk / public static mount | **Architecture** | Yes — remote engine can't write local disk |
| B4 | No persistence, no versioned result contract | **Architecture** | Yes — contract must fit UTS output |
| B5 | Credential injection across a network boundary | **Architecture** | Yes |
| B6 | Token metering tied to wall-clock ms | **Architecture** | Yes — must reconcile across engines |
| C1 | `networkidle` wait causes false failures | Medium | No |
| C2 | No FAIL verdict (all-fail reads "PARTIAL") | Medium | No |
| C3 | `chat transfer.zip` committed to git | Medium | No |
| C4 | Real client URL hardcoded in demo/docs | Medium | No |
| C5 | `SHOTS_DIR` is a relative path | Low | No |
| C6 | Hardcoded Claude model ID | Low | No |
| C7 | CORS wide open | Medium (at deploy) | No |
| C8 | No test suite for the engine itself | Medium | No |

**Recommended order once unblocked:** A1 + A2 (an hour, do first) → B1 (the pivot) →
B2 + B4 (make the UTS adapter a bounded task) → A7 (signed proofs) → A3 + A4 + A6
(required before anything public) → remaining C items.

---

## Decision gate: the UTS Global Test Magic integration

All B-items and parts of A3/A6/A7 depend on **how** UTS Global Test Magic will run.
Two candidate models:

**Model 1 — API link.** We call a UTS server over HTTPS. We submit a test job,
then poll (or receive a webhook) for status and results. Artifacts (screenshots,
logs) live on the UTS side and are fetched by reference.
- Consequences: B2's adapter is an HTTP client; B3's artifact store must *pull*
  artifacts from UTS and re-store them under our control (for auditability and
  retention); B5 needs scoped API tokens per job; A3's network egress controls
  apply only to our own Playwright engine, not UTS.

**Model 2 — hosted instance in a container.** We run a UTS instance inside our own
infrastructure (one long-lived container, or one container per run).
- Consequences: B2's adapter talks to a local/internal endpoint; B3 can use a
  shared volume or object store we own; B5 can inject secrets via container
  runtime (still short-lived, still never logged); A6's "one disposable container
  per run" pattern can cover UTS runs too; we own patching/scaling of UTS.

**What does NOT change either way** (and is therefore safe to build now):
the job model (B1), the versioned result contract (B4), the engine interface
*shape* (B2 — only the adapter internals differ), server-side signing (A7),
and every item marked UTS-independent.

---

# Section A — Bugs and security holes

## A1. Cross-site scripting (XSS) from tested websites — CRITICAL

**Where:** `frontend/index.html`, `renderProof()` (~line 183–213) and `showRunning()` (~line 171).

**Problem.** The proof screen builds HTML with template strings and assigns it via
`innerHTML`. The interpolated values include `r.target`, `s.name`, and `s.detail`.
`s.detail` contains content that originates from the *tested website* — e.g. the
title check produces `title = '<page title>'` (`backend/runner.py:87`). A malicious
site can set its `<title>` to `<img src=x onerror="...javascript...">` and that
script executes inside our origin when the proof renders. Because this product's
whole job is loading strangers' websites, assume every tested site is hostile.

**Fix steps.**

1. Never pass result data through `innerHTML`. Build DOM nodes and assign strings
   with `textContent`, which cannot execute. Replace the steps renderer:

   ```js
   function renderSteps(steps) {
     const container = document.getElementById("steps");
     container.replaceChildren();               // clear safely
     for (const s of steps) {
       const row  = document.createElement("div"); row.className = "step";
       const dot  = document.createElement("div");
       dot.className = "dot " + (s.status === "pass" ? "pass" : "fail");
       dot.textContent = s.status === "pass" ? "✓" : "✕";
       const mid  = document.createElement("div"); mid.style.flex = "1";
       const name = document.createElement("div"); name.className = "name";
       name.textContent = s.name;                 // SAFE: textContent
       const det  = document.createElement("div"); det.className = "detail";
       det.textContent = s.detail;                // SAFE: textContent
       const ms   = document.createElement("div"); ms.className = "ms";
       ms.textContent = `${s.ms} ms`;
       mid.append(name, det);
       row.append(dot, mid, ms);
       container.append(row);
     }
   }
   ```

2. Apply the same treatment to the meta block (`r.target`, `r.run_id`,
   `r.compute_ms`, `r.test_tokens`) and the verdict banner. Rule of thumb: static
   markup may use `innerHTML`; **any value that came out of a test result must go
   through `textContent`**.

3. In `showRunning()`, the check ids come from our own `/plan` response, but they
   are influenced by LLM output — treat them as untrusted too. Same pattern.

4. Defense in depth: when the frontend is served by FastAPI (or any host), add a
   Content-Security-Policy header, e.g.
   `default-src 'self'; img-src 'self' data:; script-src 'self'`.
   Note: this requires moving the inline `<script>` into a separate `.js` file
   (CSP blocks inline scripts), which is worth doing anyway.

**Verify.** Create a local test page whose title is
`<img src=x onerror="document.body.innerHTML='PWNED'">`, run a title check against
it, and confirm the proof screen shows the literal text instead of executing it.

**UTS impact:** none. Do this first regardless.

---

## A2. Run-ID collisions under concurrency — CRITICAL

**Where:** `backend/runner.py:43` (`run_id`), `runner.py:76` (screenshot filename).

**Problem.** `run_id = "run_" + now.strftime("%Y%m%d%H%M%S")` has one-second
precision. Two runs starting in the same second share a run ID; their screenshots
(`{run_id}_load.png`) overwrite each other, and once runs are persisted (B4) the
primary key collides. Guessable IDs are also an enumeration risk (see B3).

**Fix steps.**

1. Add a UUID component. Keep the timestamp prefix if you like sortable IDs:

   ```python
   import uuid
   run_id = f"run_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:12]}"
   ```

   Twelve hex chars of UUID4 is enough entropy that IDs are both collision-safe
   and non-guessable. (If IDs are ever used as the *only* access control for
   artifacts, use the full 32 chars — see B3.)

2. Screenshot filenames already derive from `run_id`, so they inherit the fix.
   Double-check nothing else assumes the old format (frontend just displays it;
   `sample_result.json` is documentation only).

3. When B4 lands, `run_id` becomes the primary key in the runs table — declare it
   `UNIQUE` so a regression collides loudly instead of silently.

**Verify.** Fire two concurrent `/run` requests (e.g. `curl` in two shells) and
confirm distinct run IDs and two separate screenshot files.

**UTS impact:** none. Note that UTS will have its own job/run identifiers — keep
*our* run_id as the canonical public ID and store the UTS-side ID as a separate
field (`engine_ref`) in the result envelope (see B4).

---

## A3. Bypassable private-host guardrail (SSRF) — CRITICAL

**Where:** `backend/app.py:67` (`is_allowed_target`), `backend/runner.py:72`
(navigation follows redirects unchecked).

**Problem.** The guardrail only string-inspects the hostname. Known bypasses:

- **Shorthand / exotic IP literals:** `127.1`, `2130706433` (decimal for
  127.0.0.1), `0x7f000001`. `ipaddress.ip_address()` raises `ValueError` on these,
  so they're treated as hostnames and allowed — but Chromium resolves them to
  localhost.
- **Public DNS names resolving to private IPs:** `127.0.0.1.nip.io`, or an
  attacker's own domain with an A record of `10.0.0.5`. The string check passes;
  the browser connects to internal infra.
- **DNS rebinding:** the name resolves public at check time, private at fetch time.
- **Redirects:** an allowed public URL 302s to `http://169.254.169.254/` (cloud
  metadata) or an internal host; the runner follows it and even screenshots the
  result.
- **Schemes:** nothing restricts the scheme; only `http`/`https` should ever
  reach the browser.

**Fix steps (application layer — do these regardless of UTS model).**

1. Enforce the scheme first:

   ```python
   ALLOWED_SCHEMES = {"http", "https"}

   def is_allowed_target(url: str) -> bool:
       try:
           parsed = urllib.parse.urlparse(url)
       except Exception:
           return False
       if parsed.scheme not in ALLOWED_SCHEMES:
           return False
       host = parsed.hostname or ""
       if not host:
           return False
       ...
   ```

2. Resolve the hostname yourself and check **every** resulting address:

   ```python
   import socket, ipaddress

   def _resolves_to_public_only(host: str) -> bool:
       try:
           infos = socket.getaddrinfo(host, None)
       except socket.gaierror:
           return False                      # unresolvable -> reject
       for info in infos:
           ip = ipaddress.ip_address(info[4][0])
           if (ip.is_private or ip.is_loopback or ip.is_link_local
                   or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
               return False
           # IPv4-mapped IPv6 (::ffff:10.0.0.1) hides a private IPv4
           if ip.version == 6 and ip.ipv4_mapped is not None:
               v4 = ip.ipv4_mapped
               if v4.is_private or v4.is_loopback or v4.is_link_local:
                   return False
       return True
   ```

   This also fixes the shorthand-literal bypass: `getaddrinfo("127.1", None)`
   resolves to `127.0.0.1`, which the IP check then rejects.

3. **Handle redirects in the runner.** After navigation completes, re-validate the
   final URL before doing anything else (screenshot included):

   ```python
   r = page.goto(target_url, wait_until="load", timeout=45000)
   if not is_allowed_target(page.url):
       raise RuntimeError(f"redirected to a disallowed target: {page.url}")
   ```

   For stronger coverage (sub-resource requests, JS-initiated fetches to internal
   hosts), add a Playwright route hook that aborts requests to private IP
   literals: `page.route("**/*", check_and_abort)`. This cannot fully solve DNS
   rebinding at the application layer — that's what step 4 is for.

4. **Network layer (the real fix — this part depends on the UTS decision).**
   Application-level checks are best-effort; the robust control is egress
   filtering on the machine that runs the browser: block RFC1918, loopback,
   link-local, and the cloud metadata IP (`169.254.169.254`) at the
   firewall/container-network level.
   - *UTS Model 1 (API link):* apply egress rules only to our own Playwright
     runner host. UTS's server is their responsibility (confirm contractually
     that they sandbox targets).
   - *UTS Model 2 (hosted container):* apply the same egress-filtered network
     to the UTS container — one Docker network with an iptables/nftables deny
     list covers both engines.

**Verify.** All of these must be rejected: `http://127.1/`, `http://2130706433/`,
`https://127.0.0.1.nip.io/`, `file:///etc/passwd`, `ftp://x/`, plus a test page
that 302-redirects to `http://10.0.0.1/`.

---

## A4. No rate limiting — open LLM and compute drain — HIGH

**Where:** `backend/app.py` — `/plan` and `/run` endpoints.

**Problem.** Both endpoints are unauthenticated. `/plan` makes a paid Anthropic
API call per request — anyone who finds the URL can drain the account. `/run`
launches a full Chromium per request — free compute and a DoS vector (each run
holds a threadpool worker for up to ~45s and a few hundred MB of RAM).

**Fix steps.**

1. Add `slowapi` (Starlette-compatible limiter):

   ```python
   # requirements.txt: slowapi>=0.1.9
   from slowapi import Limiter, _rate_limit_exceeded_handler
   from slowapi.errors import RateLimitExceeded
   from slowapi.util import get_remote_address

   limiter = Limiter(key_func=get_remote_address)
   app.state.limiter = limiter
   app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

   @app.post("/plan")
   @limiter.limit("10/minute")
   def plan(request: Request, req: PlanRequest): ...

   @app.post("/run")
   @limiter.limit("5/minute;30/day")
   def run(request: Request, req: RunRequest): ...
   ```

   Note `slowapi` requires the `request: Request` parameter to be present.

2. Cap **concurrent** browser runs with a semaphore so N parallel requests can't
   exhaust memory (each Chromium is ~200–400 MB):

   ```python
   import threading
   RUN_SLOTS = threading.BoundedSemaphore(int(os.environ.get("MAX_CONCURRENT_RUNS", "3")))

   # in the endpoint:
   if not RUN_SLOTS.acquire(blocking=False):
       raise HTTPException(429, "Server busy — try again in a minute.")
   try:
       result = run_test(...)
   finally:
       RUN_SLOTS.release()
   ```

3. Add a hard **daily LLM budget**: a simple counter (in-process for the demo,
   Redis later) that short-circuits `/plan` to the quick-pick fallback once N
   LLM calls/day are exceeded. `/plan` already has a non-LLM path — use it as
   the degraded mode rather than erroring.

4. If you're behind a proxy/load balancer at deploy time, configure the real
   client IP (`X-Forwarded-For`) or the limiter will lump everyone together.

**Verify.** Loop `curl` against `/plan` and confirm HTTP 429 after the limit;
start 4 simultaneous `/run`s with `MAX_CONCURRENT_RUNS=3` and confirm the 4th
gets 429 immediately.

**UTS impact:** none for the API-side limiting. When UTS executes tests, the
semaphore moves from "local Chromium slots" to "in-flight UTS jobs" — same
pattern, different resource.

---

## A5. Unhandled LLM failures return raw 500s — HIGH

**Where:** `backend/app.py:104–116`.

**Problem.** Only JSON-parse failure is caught. If `ANTHROPIC_API_KEY` is unset,
`anthropic.Anthropic()` raises at construction; if the API call itself fails
(rate limit, network, model deprecated), the exception propagates as a raw 500.
The demo dies at the worst moment instead of degrading.

**Fix steps.**

1. Wrap the entire LLM path and fall back to safe defaults:

   ```python
   import logging
   log = logging.getLogger("taas")

   DEFAULT_CHECKS = ["page_load", "title"]

   def _plan_with_llm(description: str) -> list[str] | None:
       """Returns check ids, or None if the LLM is unavailable/unusable."""
       try:
           client = anthropic.Anthropic()      # raises if key missing
           msg = client.messages.create(
               model=LLM_MODEL,                # see C6 — from env
               max_tokens=200,
               system=PLAN_SYSTEM_PROMPT,
               messages=[{"role": "user", "content": description}],
           )
           text = "".join(b.text for b in msg.content if b.type == "text")
           text = text.replace("```json", "").replace("```", "").strip()
           checks = [c for c in json.loads(text) if c in SUPPORTED_CHECKS]
           return checks or None
       except Exception as e:
           log.warning("LLM planning failed, falling back: %r", e)
           return None

   # in the endpoint:
   checks = _plan_with_llm(req.description) or DEFAULT_CHECKS
   source = "llm" if checks is not DEFAULT_CHECKS else "fallback"
   return {"checks": checks, "source": source}
   ```

2. Surface the degradation honestly: `"source": "fallback"` lets the frontend
   show "we ran a standard check set" instead of pretending the free text was
   understood.

3. Validate the key at startup, not first request: a startup event that logs a
   loud warning if `ANTHROPIC_API_KEY` is missing, so the operator finds out at
   boot rather than from a user-facing failure.

**Verify.** Unset `ANTHROPIC_API_KEY`, POST a free-text `/plan`, confirm HTTP 200
with `{"checks": ["page_load","title"], "source": "fallback"}` and a warning in
the server log.

**UTS impact:** none.

---

## A6. Chromium runs with `--no-sandbox` — HIGH

**Where:** `backend/runner.py:62`.

**Problem.** The browser's security sandbox is disabled while loading untrusted
web content. If a tested site exploits a Chromium vulnerability, the payload runs
directly as the backend process user. For a product that exists to load
arbitrary strangers' URLs, this is the single biggest blast-radius risk.

**Fix steps.**

1. **Local/dev:** remove `--no-sandbox` entirely. On a desktop OS Playwright's
   Chromium sandbox works out of the box:

   ```python
   launch_kwargs = {}          # sandbox ON by default
   ```

2. **Containerized deploy:** `--no-sandbox` is usually added because containers
   run as root. Don't disable the sandbox — run as a non-root user instead.
   Dockerfile pattern:

   ```dockerfile
   FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
   # image ships with a non-root 'pwuser' and all browser deps
   WORKDIR /app
   COPY backend/ /app/
   RUN pip install -r requirements.txt
   USER pwuser
   CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
   ```

   If the kernel blocks Chromium's user-namespace sandbox (some hosts), prefer
   enabling unprivileged user namespaces or a seccomp profile over
   `--no-sandbox`. Treat `--no-sandbox` as a last resort that must be paired
   with step 3.

3. **Per-run isolation (the end state — tied to the UTS decision).** The README
   already promises "one disposable container per run." Architecture: the API
   never runs a browser in-process; it dispatches a job (B1) to a runner
   container that is created for the run and destroyed after. This contains any
   browser escape to a throwaway environment and is also exactly the shape UTS
   Model 2 needs — decide once, build once.

**Verify.** `python runner.py https://example.com` without `--no-sandbox`
completes 5/5. In the container, `whoami` returns `pwuser` and a run passes.

---

## A7. The "tamper-evident hash" is not tamper-evident — HIGH (core product claim)

**Where:** `backend/runner.py:128–129`; frontend copy ("signed, timestamped
record"); `docs/sample_result.json`.

**Problem.** Three separate flaws:

1. The SHA-256 is stored *inside the same JSON it hashes*. Anyone who edits the
   trace recomputes the hash in one line. A hash only proves integrity if the
   verifier gets it through a channel the attacker doesn't control.
2. The hash covers only `run["steps"]` — the target URL, verdict, timestamps,
   run_id, and token cost can all be altered without breaking it.
3. Nothing is persisted server-side, so there is nothing to verify a customer's
   copy against later. And nothing is *signed*, despite the marketing copy.

**Fix design.** (Implement after B1/B4 exist — signing belongs in the
orchestrator, **never** inside an engine, so proofs stay engine-agnostic and UTS
results get identical treatment.)

1. **Canonical envelope.** Define the byte-exact serialization that gets hashed:
   the complete result envelope (B4) minus the `proof` block itself, serialized
   with `json.dumps(env, sort_keys=True, separators=(",", ":"))`. Canonical
   serialization matters — hash the bytes, not the dict.

2. **Sign server-side.** Start with HMAC (single secret, zero infrastructure):

   ```python
   import hmac, hashlib, os

   SIGNING_KEY = os.environ["PROOF_SIGNING_KEY"].encode()   # 32+ random bytes

   def sign_result(envelope: dict) -> dict:
       payload = canonical_bytes(envelope)
       return {
           "alg": "HMAC-SHA256",
           "digest": hashlib.sha256(payload).hexdigest(),
           "signature": hmac.new(SIGNING_KEY, payload, hashlib.sha256).hexdigest(),
           "key_id": "k1",          # enables key rotation later
       }
   ```

   Upgrade path when customers need *independent* verification: Ed25519
   signatures (`cryptography` lib) with a published public key — customers can
   then verify proofs without trusting our server. HMAC first, Ed25519 when a
   customer actually asks.

3. **Persist the proof server-side** (B4's runs table stores the envelope and
   its proof block). The signed record on our side is the anchor; the customer's
   download is a convenience copy.

4. **Add a verification endpoint** — this is a sellable feature:

   ```
   POST /verify   body: a full result envelope
   -> {"valid": true, "run_id": ..., "signed_at": ...}
   ```

   It recomputes the canonical bytes, checks the signature, and (if the run
   exists) confirms the stored copy matches.

5. **Fix the copy or the code — never ship the mismatch.** Until signing exists,
   the frontend must not say "signed." Change the copy to "timestamped,
   hash-chained record" only *after* the hash actually covers the whole envelope.

6. Remove `trace_sha256` computation from `runner.py` once orchestrator signing
   is live (engines report results; the platform notarizes them).

**Verify.** Tamper with one byte of a stored result and confirm `/verify`
rejects it; confirm `verdict`, `target`, and timestamps are all inside the
signed payload.

---

# Section B — Architecture (the UTS Global Test Magic runway)

## B1. Replace synchronous `/run` with an async job model — THE PIVOT

**Where:** `backend/app.py:128` (`/run`), frontend `runFlow()`.

**Problem.** `/run` blocks for the whole test (up to minutes). An external UTS
engine is submit-then-poll by nature — a blocking request/response can't
represent it. The blocking call also can't stream live step progress (the
"watch it run" moment in the README is currently faked with static dots), holds
a server thread per run, and gives the browser fetch a long timeout window.

**Fix design.**

1. **New endpoints** (keep `/run` temporarily as a compatibility shim that
   internally creates a job and waits):

   ```
   POST /runs                 body: {url, checks, engine?}   -> 202 {run_id}
   GET  /runs/{run_id}        -> full result envelope (status: queued|running|done|error)
   GET  /runs/{run_id}/events -> Server-Sent Events stream of step updates
   ```

2. **Job store.** Demo scale: a dict guarded by a lock, replaced by the SQLite
   runs table from B4 as soon as it exists (do B4 together with B1 — a job *is*
   a row).

3. **Execution.** Demo scale: `ThreadPoolExecutor(max_workers=MAX_CONCURRENT_RUNS)`
   in the FastAPI process; the worker calls the engine adapter (B2) and updates
   the job row as steps complete. Production scale: a real queue (e.g. Redis +
   worker process) — but **do not** build the queue before it's needed; the
   endpoint contract above is what matters, because the frontend and the UTS
   adapter both code against it, not against the executor.

4. **Live steps.** Give the engine adapter an `on_step(step_dict)` callback;
   `runner.py`'s internal `step()` helper already produces exactly the right
   dict — call the callback inside it. The SSE endpoint replays stored steps
   then tails new ones:

   ```python
   from sse_starlette.sse import EventSourceResponse   # sse-starlette pkg

   @app.get("/runs/{run_id}/events")
   async def run_events(run_id: str):
       async def gen():
           async for step in job_store.stream_steps(run_id):
               yield {"event": "step", "data": json.dumps(step)}
           yield {"event": "done", "data": json.dumps(job_store.result(run_id))}
       return EventSourceResponse(gen())
   ```

5. **Frontend:** `runFlow()` becomes: POST `/runs` → open
   `new EventSource(API + "/runs/" + id + "/events")` → tick each step green as
   its event arrives → render the proof on the `done` event. Keep a
   poll-`GET /runs/{id}`-every-2s fallback for environments that block SSE.

6. **Timeouts:** enforce a hard per-run wall-clock cap in the orchestrator
   (e.g. 3 minutes → mark run `error: timeout`, kill the engine job). Never rely
   only on the engine's internal timeouts.

**Why safe to design now:** both UTS models (API link or hosted container) sit
behind this identical contract. Only step 3's executor internals differ.

---

## B2. Engine abstraction layer — where the UTS adapter plugs in

**Where:** `backend/app.py:29` (direct `from runner import run_test`),
`SUPPORTED_CHECKS` duplicated in `app.py:47` and `runner.py:37`.

**Problem.** The API is welded to the local Playwright engine. Check vocabulary
is hardcoded in two places. Plugging in UTS today would mean rewriting the API
layer, which is exactly the rework the README warned against.

**Fix design.**

1. **Define the interface** (new file `backend/engines/base.py`):

   ```python
   from typing import Protocol, Callable

   class TestEngine(Protocol):
       name: str

       def capabilities(self) -> list[dict]:
           """Check ids this engine supports, with human labels.
           e.g. [{"id": "page_load", "label": "Page loads", "read_only": True}]"""

       def start(self, job: "TestJob", on_step: Callable[[dict], None]) -> str:
           """Begin execution. Returns an engine-side reference id.
           MUST be non-blocking for remote engines; MAY block for local ones
           (the orchestrator calls it from a worker thread either way)."""

       def status(self, engine_ref: str) -> str:
           """queued | running | done | error"""

       def result(self, engine_ref: str) -> dict:
           """The raw engine result, to be normalized into the envelope (B4)."""

       def cancel(self, engine_ref: str) -> None: ...
   ```

2. **Adapter #1 — Playwright** (`backend/engines/playwright_engine.py`): wraps
   the existing `run_test()` almost unchanged. `start()` runs it and fires
   `on_step` from inside the runner's `step()` helper. `runner.py` itself stays
   the proven engine; it just stops being imported by the API directly.

3. **Adapter #2 — UTS Global Test Magic** (`backend/engines/uts_engine.py`,
   skeleton only until the integration model is cemented):
   - *Model 1 (API link):* `start()` POSTs the job to the UTS endpoint and
     returns their job id; `status()`/`result()` poll their API (or a webhook
     receiver updates the job store); artifacts are downloaded by reference and
     handed to the artifact store (B3). Config: `UTS_BASE_URL`, `UTS_API_TOKEN`.
   - *Model 2 (hosted container):* identical adapter code pointed at the
     internal container endpoint (`http://uts:9000` on the Docker network), plus
     a lifecycle hook if we go one-container-per-run.
   - Either way the adapter's job is **translation**: UTS's native result format
     → our envelope (B4). No UTS concept may leak past the adapter.

4. **Registry + routing** (`backend/engines/__init__.py`):

   ```python
   ENGINES = {"playwright": PlaywrightEngine(), "uts": UTSEngine()}
   DEFAULT_ENGINE = os.environ.get("DEFAULT_ENGINE", "playwright")
   ```

   `SUPPORTED_CHECKS` is deleted as a global; `/plan` asks the selected engine's
   `capabilities()` for the valid-id list (the LLM prompt is built from it, so a
   new engine's checks become plannable with zero prompt changes).

5. **Job routing rule** lives in the orchestrator (B1): per-request `engine`
   field, falling back to the default. Later this is where "legacy system tests
   → UTS, plain web checks → Playwright" routing logic goes.

**Verify.** The API layer must have zero imports from `runner.py`; swapping
`DEFAULT_ENGINE` must require no frontend change; a mock engine (returns canned
steps) should pass the full frontend flow — that mock is also your test fixture
for C8.

---

## B3. Artifact storage — screenshots can't live on local disk

**Where:** `backend/runner.py:76–80` (writes PNGs to local dir),
`backend/app.py:45` (public `StaticFiles` mount), `app.py:139` (URL rewriting).

**Problem.** Three issues: (a) a remote UTS engine cannot write into the API
server's disk, so the current path breaks the moment tests run elsewhere;
(b) `/shots` is a public directory with guessable names — anyone can enumerate
customers' screenshots; (c) the directory grows forever, no retention.

**Fix design.**

1. **Interface** (`backend/artifacts.py`):

   ```python
   class ArtifactStore(Protocol):
       def put(self, run_id: str, name: str, data: bytes, mime: str) -> str:
           """Store bytes, return an artifact_id."""
       def get(self, artifact_id: str) -> tuple[bytes, str]: ...
       def delete_run(self, run_id: str) -> None: ...
   ```

   Engines and adapters hand artifact *bytes* (or fetch-by-reference for UTS
   Model 1) to the store; results carry `artifact_id`s, never file paths.

2. **Implementations.** `LocalArtifactStore` (files under a data dir, an
   index in the runs DB) now; `S3ArtifactStore` (any S3-compatible bucket —
   AWS, R2, MinIO if self-hosted next to a UTS container) when deployment is
   real. The runner's `shots_dir` parameter goes away — the Playwright adapter
   captures `page.screenshot()` **as bytes** (no `path=`) and calls `put()`.

3. **Access-controlled serving.** Replace the static mount with an endpoint:

   ```
   GET /runs/{run_id}/artifacts/{artifact_id}
   ```

   Demo-tier access control: run_id acts as a bearer capability, so it must be
   unguessable (full UUID — see A2). Post-signup: check the session owns the run.
   Set `Content-Disposition: inline` and the stored MIME type.

4. **Retention.** A daily cleanup task (`delete_run` for runs older than N days
   on the free tier). Decide N alongside the audit-retention promise — signed
   proofs (A7) may need the *envelope* kept long after screenshots expire; the
   envelope should therefore store artifact **hashes** so a proof remains
   verifiable even after the heavy bytes are deleted.

5. **UTS specifics.** Model 1: the adapter downloads each artifact from UTS
   (authenticated), stores it via `put()` — we must own our copies; audit proofs
   can't depend on another company's retention policy. Model 2: mount a shared
   volume or point UTS output at MinIO; same `put()` call either way.

---

## B4. Persistence + a versioned result contract

**Where:** nothing persists today; the result shape is implicit in `runner.py`
and consumed loosely by the frontend.

**Problem.** "An auditable proof you can keep" that nobody keeps: results exist
only in the HTTP response. There is also no named contract for what a result
*is* — which becomes acute the moment a second engine (UTS) must produce
compatible output.

**Fix design.**

1. **Result envelope v1** — write this schema down as `docs/RESULT_SCHEMA.md`
   and treat it as an API contract:

   ```jsonc
   {
     "schema_version": 1,
     "run_id": "run_20260715_ab12cd34ef56",
     "status": "done",                  // queued|running|done|error
     "target": "https://example.com",
     "engine": {"name": "playwright", "version": "1.49", "ref": null},
                                        // ref = engine-side job id (UTS's id)
     "requested_checks": ["page_load", "title"],
     "started_utc": "...", "finished_utc": "...",
     "steps": [
       {"name": "...", "check_id": "page_load", "status": "pass",
        "detail": "...", "ms": 5240, "artifacts": ["art_..."]}
     ],
     "verdict": "PASS",                 // PASS | FAIL | PARTIAL  (see C2)
     "steps_passed": 5, "steps_total": 5,
     "metering": {"units": 5, "basis": "per-check-v1"},   // see B6
     "proof": {"alg": "HMAC-SHA256", "digest": "...", "signature": "...", "key_id": "k1"}
   }
   ```

   Rules: additive changes only within a version; any breaking change bumps
   `schema_version`; the frontend and the UTS adapter both code to this file.
   Note `check_id` is added to steps (today only the display name exists) — the
   UTS adapter needs a stable id to map onto, not an English sentence.

2. **Runs table** (SQLite via `sqlite3` or SQLAlchemy — SQLite is genuinely fine
   until multi-instance deploy):

   ```sql
   CREATE TABLE runs (
     run_id      TEXT PRIMARY KEY,
     status      TEXT NOT NULL,
     engine      TEXT NOT NULL,
     target      TEXT NOT NULL,
     created_utc TEXT NOT NULL,
     envelope    TEXT,            -- full result JSON once done
     UNIQUE(run_id)
   );
   CREATE TABLE artifacts (
     artifact_id TEXT PRIMARY KEY,
     run_id      TEXT REFERENCES runs(run_id),
     name TEXT, mime TEXT, sha256 TEXT, path TEXT
   );
   ```

3. This table doubles as B1's job store (status transitions) and A7's proof
   anchor (the stored envelope is what `/verify` compares against).

4. **Migration note:** `runner.py`'s current output keys mostly map 1:1 — the
   Playwright adapter (B2) does the reshaping; `runner.py` itself needs almost
   no changes beyond emitting `check_id` per step.

---

## B5. Credential injection across a network boundary

**Where:** future feature; pattern documented in `docs/CREDENTIALS.md`.

**Problem.** The vault doc's runtime-injection step assumes the runner is a
local disposable container we control ("inject as env var into the container").
With UTS Model 1, the secret would cross the network to another company's
server; with Model 2, it crosses into a container we host but didn't write.
Env-var injection is also visible to anything that can read `/proc` in the
container.

**Fix design (decide alongside the UTS contract).**

1. Vault fundamentals stay as documented: per-tenant encryption, ciphertext at
   rest, operator-blind, decrypt only at run time. Nothing here changes.
2. *Model 2 (hosted UTS container):* prefer file-based secret mounts (tmpfs,
   e.g. Docker/K8s secrets) over env vars; the file disappears with the
   container. Short-lived: written at job start, shredded at job end.
3. *Model 1 (UTS API):* never send raw customer credentials to a third-party
   API unless the contract explicitly covers it (processing agreement, their
   vault posture audited). Prefer alternatives in this order: (a) UTS-side
   vault with *their* per-job injection and our per-job scoped token to
   activate it; (b) session handoff — we perform the login in our own
   Playwright engine, then pass the short-lived session cookie/token to UTS
   instead of the password; (c) raw credential transfer over mTLS as last
   resort, contractually bound, with immediate-deletion guarantees.
4. Either model: credentials never appear in the envelope, logs, step details,
   or screenshots (mask password fields before capture — Playwright:
   `page.locator("input[type=password]").evaluate("e => e.style.filter='blur(8px)'")`
   or screenshot with `mask=[locator]`).
5. Log an audit event (who/when/which credential id — never the value) for
   every injection.

---

## B6. Token metering — decouple from wall-clock milliseconds

**Where:** `backend/runner.py:131–133`.

**Problem.** `test_tokens = total_ms / 100` bills the customer for *their own
site being slow* (network wait dominates, not our compute), is trivially skewed
by timeouts (a 45s hang = 450 tokens for zero work), and will never reconcile
across engines — UTS's step timings will have completely different baselines,
so identical tests would cost wildly different amounts depending on routing.

**Fix design.**

1. Meter **per check executed**, with a fixed unit price per check type:

   ```python
   CHECK_UNITS = {"page_load": 3, "title": 1, "https": 1,
                  "login_present": 2, "performance": 1}
   units = sum(CHECK_UNITS.get(s["check_id"], 1) for s in steps)
   ```

   Deterministic, explainable on an invoice, identical across engines — which
   is precisely what a product called "Test by Token" needs its unit to be.

2. Record the basis in the envelope (`"metering": {"units": 5, "basis":
   "per-check-v1"}`) so historical runs stay interpretable when pricing evolves.

3. Keep `compute_ms` as **internal telemetry** (it's our cost input for setting
   unit prices) but remove it from the billing math. When UTS runs a test,
   record UTS's charge to us alongside — the margin per check type falls out of
   the data.

4. Metering computation lives in the orchestrator (like signing — A7), never in
   engines.

---

# Section C — Smaller fixes

## C1. `networkidle` causes false failures

**Where:** `backend/runner.py:72`.
**Problem:** sites with websockets/long-polling/analytics never reach network
idle → 45s timeout → healthy site reported as failing. Playwright's own docs
discourage `networkidle`.
**Fix:** navigate with `wait_until="load"`, then wait for meaningful content
instead of network silence:

```python
r = page.goto(target_url, wait_until="load", timeout=30000)
try:
    page.wait_for_load_state("networkidle", timeout=5000)  # bonus, not required
except PlaywrightTimeoutError:
    pass                                                   # busy sites are fine
page.wait_for_timeout(1500)                                # SPA hydration pause
```

Keep the hydration pause — that lesson was hard-won (blank SPA screenshots).
**Verify:** run against a site with an open websocket (any live-chat widget) and
confirm PASS in seconds instead of a 45s timeout.

## C2. No FAIL verdict

**Where:** `backend/runner.py:126`.
**Problem:** 0/5 passed still reads "PARTIAL" — undercuts credibility.
**Fix:**

```python
if run["steps_passed"] == run["steps_total"]:
    run["verdict"] = "PASS"
elif run["steps_passed"] == 0:
    run["verdict"] = "FAIL"
else:
    run["verdict"] = "PARTIAL"
```

Add matching FAIL styling in the frontend (red banner already exists as
`.verdict.partial`; add a distinct `.verdict.fail`). Envelope v1 (B4) already
reserves all three values.

## C3. `chat transfer.zip` committed to git

**Where:** repo root, in history since the initial commit.
**Problem:** chat logs/handover material baked into the repository — noise at
best, sensitive at worst, and it goes wherever the repo is pushed.
**Fix steps:** (1) `git rm "chat transfer.zip"` + commit; (2) add `*.zip` to
`.gitignore`; (3) note that the file remains in *history* — if the repo is ever
pushed anywhere shared, rewrite history first (`git filter-repo --path
"chat transfer.zip" --invert-paths`) **before** the first push; after any
rewrite, collaborators must re-clone.

## C4. Real client URL hardcoded

**Where:** `frontend/index.html:74` (input default) and
`docs/sample_result.json` (target + page title).
**Problem:** a real client's product URL and name ship inside a public demo.
**Fix:** default the input's `value` to empty with the placeholder
`https://your-site.com`; regenerate `sample_result.json` against a neutral
target (e.g. `https://example.com`) — one `python runner.py https://example.com`
produces a fresh sample.

## C5. `SHOTS_DIR` is a relative path

**Where:** `backend/app.py:43`, `runner.py` default.
**Problem:** `./shots` resolves against the process CWD — start uvicorn from
the repo root instead of `backend/` and screenshots land in a different folder
than the static mount serves.
**Fix:** anchor to the file:

```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHOTS_DIR = os.environ.get("SHOTS_DIR", os.path.join(BASE_DIR, "shots"))
```

(Note: superseded entirely by B3, but it's a two-line guard worth having until
then.)

## C6. Hardcoded Claude model ID

**Where:** `backend/app.py:112` (`claude-sonnet-4-6`).
**Problem:** model ids deprecate; a retired id turns into runtime 400s (masked
today by A5's missing error handling). Current generation is `claude-sonnet-5`.
**Fix:** `LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5")`, used by
the `/plan` path; document it in `docs/SETUP.md` next to `ANTHROPIC_API_KEY`.
Verify the pinned id against Anthropic's current model list at implementation
time rather than trusting this doc.

## C7. CORS wide open

**Where:** `backend/app.py:34–39`.
**Problem:** `allow_origins=["*"]` — fine locally, wrong deployed.
**Fix:** `allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5500").split(",")`,
set the env var to the real frontend origin at deploy. If the frontend ends up
served *by* FastAPI (same origin), CORS middleware can be dropped entirely.

## C8. No test suite

**Where:** the whole repo — a testing product with zero tests of itself.
**Problem:** every fix above lands blind without a regression net.
**Fix steps:**

1. `pip install pytest`; create `backend/tests/`.
2. **Pure-logic tests first** (fast, no browser): `is_allowed_target` against
   the full A3 bypass list; verdict logic (C2); metering (B6); envelope
   canonicalization + signature round-trip (A7).
3. **API tests** with FastAPI's `TestClient` and the mock engine from B2 —
   `/plan` fallback behavior (A5), `/runs` lifecycle (B1), 429s (A4).
4. **One real engine smoke test**, marked `@pytest.mark.slow`: serve a tiny
   static page from the test itself (`http.server` on localhost — note the
   engine test must bypass/allowlist localhost for this), run `page_load` +
   `title` against it, assert 2/2. This is the only test that needs Chromium.
5. Wire into CI whenever a remote repo exists (GitHub Actions:
   `pytest -m "not slow"` on every push; the slow marker nightly).

---

## Appendix — target file layout after B-items land

```
backend/
  app.py                  # HTTP layer only: routes, validation, rate limits
  orchestrator.py         # job lifecycle, engine routing, signing, metering
  engines/
    base.py               # TestEngine protocol
    playwright_engine.py  # adapter #1 (wraps runner.py)
    uts_engine.py         # adapter #2 (UTS Global Test Magic — API or container)
  runner.py               # the proven Playwright engine, unchanged at heart
  artifacts.py            # ArtifactStore protocol + local/S3 impls
  store.py                # SQLite runs/artifacts persistence
  tests/
docs/
  RESULT_SCHEMA.md        # envelope v1 — the cross-engine contract
```
