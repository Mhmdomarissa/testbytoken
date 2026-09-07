# Review environment — UTS engine inside Test by Token

What was built on 17 Aug 2026: the second customer touchpoint. They have seen the
homepage, signed up, and are running their first real application test — with the
UTS engine doing the work, one engine per user, and an interactive login so they
can get past MFA without ever handing us a password.

## Start it

Two processes, both one `make` command away from the repo root (or use
`.claude/launch.json`, which defines both):

```bash
make setup-api setup-engine   # first time only
make api                       # port 8001
make web                        # port 5500
```

Then open **<http://localhost:5500/console.html>**.

The homepage (`index.html`) is untouched and still runs the original Playwright
checks. The console is a separate, deliberately plain page — the click-through
shape is what is being reviewed here, not the visual design.

## What to try

1. **Start typing a URL.** The workspace pill fills in and the engine pill goes
   `warm` within about 3.5s. That is your engine booting and Chrome pre-launching
   while you type, so pressing scan costs a navigation and not a browser start.
2. **Leave "I'll sign in myself" selected** and scan. A Chrome window opens at
   your login page and the run *parks*. Sign in there — password, OTP, 2FA,
   CAPTCHA, SSO, whatever the app demands — then press **I've signed in**.
   Nothing is captured while you type. Only the resulting session is kept, and
   the console reports a cookie *count*, never a value.
3. **Pick modules** from what the crawl found, then generate and run. Steps
   stream live; the result table shows every test case, every step, and links to
   the engine's own HTML report.

A no-login target works too — the handoff detects there is no login form and
carries straight on.

## What is actually wired

```
first keystroke   POST   /uts/workspace              boot engine, warm Chrome
scan              POST   /uts/scan                   {url, interactive}
live progress     GET    /uts/jobs/{id}/events       SSE, resumable via ?since=
login done        POST   /uts/jobs/{id}/continue     no credentials cross this line
look inside       POST   /uts/inspect                {module} — enumerate one page
run               POST   /uts/run                    {modules:[...]}
result            GET    /uts/jobs/{id}
report            GET    /uts/jobs/{id}/report       engine's HTML report
reset             POST   /uts/workspace/{id}/reset   kill a wedged run, clean engine
teardown          DELETE /uts/workspace/{id}
debug             GET    /uts/debug/workspaces
```

All of this is implemented in `services/api/tbt_api/routes/uts.py`, backed by
`services/api/tbt_api/engines/uts_workspace.py`.

### Reset engine

A button in the console header, and `POST /uts/workspace/{id}/reset` behind it.
A job only clears itself when a result or error event arrives, so an engine that
dies mid-run used to leave the workspace permanently "already running a test".
Reset kills the engine, marks the stranded job cancelled and brings a clean one
up under the same session. `submit()` also self-heals now: if a job is claimed
but the process is dead, the claim is dropped rather than refusing work forever.

### Look inside a module

The scan tells you a module exists. **Look inside** clicks into it and inventories
what is actually there — tabs, links, action buttons, form fields, search boxes —
each with the locator the runner would use, rendered as a table per group.

It composes the engine's own detectors (`_find_nav_links`, `_find_action_buttons`,
`_find_form_fields`, `_find_search_fields`, `_find_sub_nav_links`) rather than
adding a second crawler. It honours the same login path as scan and run, and
**the only thing it clicks is the module's own nav link** — pressing arbitrary
buttons on a customer's application could submit forms or write data.

Each user's artifacts land in `workspaces/<session>/` — `generated/`, `reports/`,
`logs/`, exports. Two users never share a directory.

## Verified working

| | |
|---|---|
| Engine fork | 1,328 files → 41, no Flask, its own venv |
| Per-user isolation | 17 hardcoded paths now resolve from `UTS_WORKDIR` |
| Warm start | host boots 0.16s, Chrome warm 3.56s |
| Interactive login | parks, resumes on signal, captures session |
| Session carry-over | survives all 3 browser restarts in one chain |
| Full chain | scan → generate → execute → per-step results → HTML report |
| Client independence | killing the client mid-run does not stop the engine |

The full chain was proven against the bundled demo fixture:
`TC_AI_LINK_Transfers`, 7 steps, 6 pass / 1 fail, with per-step action, status,
message and duration coming back through the API. TimeSight itself still needs a
real login, which is what the handoff is for.

## Fixed after the first live run against TimeSight

The first real run generated and executed its whole suite against a **blank
tab**. Every test case read `Navigate — Application URL = 'data:,'`, the crawl
reported `0 pages across 0 modules`, and each click then failed for two minutes.
Four separate defects stacked up; all four are fixed.

### 1. Race on the browser singleton — the `data:,` root cause

`services/engine/uts_engine/automation/selenium_session.py` keeps `_driver` as
a module global, reached from both the pre-warm thread and the job thread with
**no synchronisation**. The event order in the log (`busy` → `warming` →
`warm`) shows both running at once: the job navigated one driver while the warm
thread created another, and the un-navigated one — sitting on Chrome's `data:,`
startup page — is what discovery crawled.

**Fixed.** An `RLock` now serialises every create/replace/quit, `quit_driver()`
is split so the locked path cannot deadlock, and `EngineHost.warm()` refuses to
warm while a job holds the browser.

### 2. A blank tab could be mistaken for the application

`login_handoff` returned `driver.current_url` unconditionally, so `data:,`
propagated into discovery as the target URL.

**Fixed.** `services/engine/uts_engine/host.py`'s `_real_url()` rejects `data:,`,
`about:blank` and `chrome://newtab/`, falling back to the URL the customer
actually asked for.

### 3. Signing out between tests destroyed the captured session

`logout_after_each_test` was hardcoded `True`. That assumes stored credentials to
sign back in with — but with an interactive session there are none, so the log
reads `SESSION RESET: username/password locators missing` and every test after
the first ran unauthenticated, after burning ~25s hunting a logout button that
does not exist.

**Fixed.** The flag is now plumbed through `_build_input()` and set to
`not has_session()`, so a customer-supplied session is preserved.

### 4. Steps took minutes each

One failed click on `Inbox` took **122 seconds**.

`services/engine/uts_engine/discovery/automation_runner.py:121 _find_element()`
tries a cascade of locator strategies, and a **5s implicit wait** was charged
on every miss in that cascade, on top of the explicit `WebDriverWait(12)`.
Mixing implicit and explicit waits is a known Selenium anti-pattern; this is
the textbook symptom.

**Fixed.** `services/engine/config/selenium.json` now pins
`implicit_wait_seconds: 0` with a comment explaining why it must stay there.
Explicit waits do the waiting.

## Still open

### Generated tests assert on the app name we were given

```
5. FAIL  Verify  PostLogin  'DemoBank' not found on page — continuing
```

`services/engine/uts_engine/planning/ai_brain.py` generated a post-login
verification whose expected value was `discovery.app_name` — the label the
*customer typed into our form*. Any app that does not happen to print that
exact string failed this step. The same pattern produced
`Verify Home = 'timehseet extractor'` against TimeSight, including the
customer's own typo.

> Note (service-split pass): the current `ai_brain.py` now derives this from
> `_observed_marker()` — the crawled page title, or the post-login URL's host
> — instead of `app_name`, with a comment recording exactly this history. If
> you're touching this code, verify whether this item is actually still open
> before assuming the description above is current.

## Known gaps

- **No auth.** `session_id` is a stubbed opaque id in `localStorage`. When
  accounts land it becomes the user id and nothing else changes.
- **Session bundles are in memory only.** Encryption at rest, TTL and an access
  audit are Phase C work (`docs/UTS_INTEGRATION_PLAN.md`).
- **Interactive login is local-mode only.** The customer uses the Chrome window
  on their own machine. The hosted version needs the noVNC pane from Phase C.
- **One run per workspace at a time**, enforced deliberately — one browser per
  user.
- **ALM/Xpedite exporters still ship** in `services/engine/uts_engine/exporters/`.
  They are dead weight for this product and should be dropped; they are now
  wrapped in try/except so an export failure can no longer kill a customer's run.
- **`services/engine/config/app-input.json`** still carries another
  application's defaults. Nothing reads it — `uts_engine.host`'s
  `_build_input()` builds the input in memory — but it should go.
