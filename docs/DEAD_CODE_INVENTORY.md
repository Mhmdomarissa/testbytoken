# Dead code & follow-up inventory

Named, numbered items discovered during work on this codebase that are real
but out of scope for the change that found them. This is not a bug backlog
— that's [`bug_fixes.md`](bug_fixes.md) — it's for code that should be
replaced, merged, or removed, logged here so a future PR can reference it
by ID instead of re-discovering and re-explaining it.

The D-numbering continues from the Phase 0 "make it honest" work brief,
where D1/D2/D5 named specific locator/scenario-handling defects fixed in
that phase (see the `W5 (D1+D2+D5)` commit on `fix/phase0-honest-runner`
for what those were and how they were resolved). D3/D4/D6 were not used by
that brief.

---

## D7. Second scenario generator in discovery.py emits assertion-less Verify steps

**Where:** `services/engine/uts_engine/discovery/discovery.py` — roughly 15
`StepDef(...)` call sites that build `Verify` steps (e.g. around `~947,
1204, 1239, 1242, 1245, 1246, 1315` as of the W5 commit), all setting
`expected=...` but never the `assertion` field.

**Found while:** Phase 0's W5 (D1 — flipping `ai_pipeline.py`'s
`replace_scenarios` default from `True` to `False` so scenarios the crawl
itself observed stop being silently discarded in favor of only the
AI-generated ones).

**Problem.** `discovery.py` has its own, independent scenario/step
generator — distinct from `planning/ai_brain.py`, which Phase 0's W4
already taught to only emit an `assertion` kind sourced from something the
crawl actually observed (`url_matches`, `element_visible`, ...; see the
`W3+W4 (E3)` commit). `discovery.py`'s generator was never touched. Its
Verify steps now correctly FAIL under W3's closed assertion vocabulary
("no checkable assertion" is never a pass) instead of vacuously passing —
the right outcome given the choice, but it means every scenario this
generator produces (`TC_POS_*`, `TC_NEG_*`, and similar) is currently
guaranteed-FAIL on its own Verify steps. Confirmed live: re-enabling these
scenarios (via D1) dropped the local-fixture demo from 1/1 to 1/3 passing,
with both new failures coming from this generator, not ai_brain.py's.

**Scope note — why this wasn't fixed in Phase 0.** Teaching this generator
the same discipline as `ai_brain.py` is materially the same size of work
W4 already was: a second full pass over ~15 call sites, deciding per
branch what the crawl actually observed and can be asserted on. W5's
stated done-criterion was locators + stable ids in the page map, not a
second generator rewrite — doing this too would have been undisclosed
scope creep on an already large change.

**Fix (future).** Apply the same treatment as `ai_brain.py`'s W4 changes:
for every Verify step this generator emits, either attach a real
`assertion` kind backed by something the crawl observed (module-locator
data is already available here, the same signal
`_post_login_verify_step()` in `ai_brain.py` uses), or emit no Verify step
at all for that branch rather than one with nothing checkable.

**Phase 1 impact.** The planner work in Phase 1 needs to account for *two*
scenario generators needing eventual consolidation or replacement, not
one — worth deciding early whether `discovery.py`'s generator is kept,
merged into `ai_brain.py`'s, or retired outright, rather than maintaining
both independently going forward.

**Status:** open, unowned.

---

## D8. Cross-test logout never actually works against any app but the bundled fixture

**Where:** `services/engine/uts_engine/automation/session_reset.py:64` reads
`logout_button` from `services/engine/config/selenium.json:44`, which is
hardcoded to `{"by": "id", "value": "btn-logout"}` — the bundled local
demo fixture's own logout control id, not anything crawl-derived.

**Found while:** producing the final W0a-vs-Phase-0 OrangeHRM Admin
before/after (the headline demo artifact). The honest run reported 0/9
test cases passing, all landing on `'Username' not found — tried locator
name=username`.

**Problem.** Against any real app — OrangeHRM included — this locator
never matches anything. `session_reset.py`'s "log out between test cases"
step silently fails every time (caught, logged as "logout control not
used"), so the browser's session cookie is never actually cleared. Every
test case after the first one in a multi-case run starts already
authenticated: `Navigate` to the login URL lands on `/dashboard/index`
instead (OrangeHRM itself redirects an authenticated session away from
the login page), and the SetText Username / SetPassword / PerformClick
Login steps that follow find no login form to act on.

**Why this was invisible until now.** Two Phase-0-fixed defects were
stacked on top of it, each independently hiding it:
  - E2 (the any-locator sweep, W2): with no login form present,
    `_find_element`'s old fallback silently bound "SetText Username" and
    "PerformClick Login" to *some other* visible element on the dashboard
    and reported success. Confirmed by re-reading the **original** W0a
    baseline's own raw data: 6 of its 7 test cases' Navigate step already
    landed on `/dashboard/index`, not the login page — same defect, same
    run — yet every one of those steps reported PASS.
  - E1+E3 (vacuous assertions): the login-success Verify checked for the
    string "OrangeHRM" or "Admin", both present on literally every page
    of the app regardless of auth state, so even a step that ran against
    the wrong page still verified "true."

With both fixed, this stops being invisible and starts being nine FAILs.
That is the correct, intended behavior of the assertion/locator work —
this item is about the underlying defect the honesty work exposed, not
about the runner being wrong.

**Fix (future).** `logout_button` needs to come from what the crawl
observed for *this* app (the same treatment D2 already gave field/button/
search-box locators in the page map), not a static fixture-shaped config
file — or `session_reset.py` needs a crawl-derived fallback (e.g. search
observed buttons/links for logout-shaped text) when the configured
locator doesn't resolve, instead of silently giving up.

**Status:** open, unowned. Blocks any multi-test-case run against a real
target from producing meaningful case-level pass/fail data — every test
case after the first is currently testing "did the previous test case's
session survive," not the scenario it claims to.

---

## D10. `_find_element()` can click an element that exists but isn't actually shown

**Where:** `services/engine/uts_engine/discovery/automation_runner.py`,
`_find_element()`'s locator-based lookup: after checking for a *visible*
match, it explicitly falls back to `driver.find_elements(by, value)` and
returns the first result "even if not displayed" — the comment there says
this is deliberate, for mega-menus / off-canvas navigation.

**Found while:** diagnosing why D9's idempotent-login logic appeared to
work against the local fixture (3/3 passed) even in a build that had
`_check_auth_state()`'s SPA bug (see this file's note on that fix)
misreporting "authenticated" immediately after a *verified* logout.
Directly reproduced: with the fixture genuinely on the login screen
(confirmed via `document.getElementById('screen-dashboard')`'s active
class), calling `_find_element()` on the dashboard's "Transfers" nav
link — which is inside a `display:none` container at that point — still
returned the element, and clicking it reported `PASS`.

**Problem.** This fallback can't distinguish "hidden because a menu
hasn't been opened yet" (the case it's meant for) from "hidden because
the app genuinely isn't in the state this step assumes" (session expired,
wrong page, not authenticated). It let a click silently "succeed" against
an element that was not actually interactable in the state the app was
actually in — the same shape of problem W2 (E2) already fixed for the
any-*locator* sweep, just one layer down: this is the any-*visibility*
sweep for a single, correctly-identified locator.

**Why this wasn't fixed here.** Out of scope for D9, which is about the
login-step orchestration, not the general element-resolution fallback
chain — and this fallback has a documented, intentional reason to exist
(real mega-menu/off-canvas UIs where an element is legitimately in the
DOM but not yet visible pending an unrelated trigger). Narrowing it
correctly needs a real design decision (e.g., only fall back to a hidden
match when the step itself is inside a known "open this first" sequence),
not a quick removal — removing it outright would likely just break the
apps it was added for.

**Status:** open, unowned.

---

## D11. `_best_locator()`'s worst-case fallback isn't unique enough to find its own element

**Where:** `services/engine/uts_engine/discovery/discovery.py`'s
`_best_locator()` — when an element has no `id`, `name`, or text, it falls
back to `css = tag; css += f"[{attr}='{val}']"` for the first of
`("type", "class")` that has a value. For a bare `<input type="text">`
with no class, that produces `input[type='text']` — a selector matching
*every* such input on the page, not a unique one.

**Found while:** accounting for the final OrangeHRM Admin re-run's
remaining failures (see the D9 commit / this session's report). 5 of the
8 non-network failures (`TC_NEG_03`, `TC_AI_ENTER_Admin_D1/D2/D3`,
`TC_AI_SEARCH_Admin_D1`) were `SetText` steps on search/filter fields
whose captured `locator_value` was literally `input[type='text']`, and
`_find_element` correctly returned nothing resolvable for it (whatever it
matched wasn't the intended, currently-visible field — plausibly because
OrangeHRM's advanced-search fields for this page live behind a collapsed
panel the crawl never opened, so nothing genuinely visible matched
either).

**Problem.** This is the field-capture analog of D5 (matches-anything
XPath) and D10 (visibility blindness): a locator that's technically
"found" but not actually specific to the element the step means. Correct
behavior here — a real FAIL rather than a silent bind to the wrong input
— already happened (W1/W2 hold), so this isn't a new *honesty* bug. It's
a coverage gap: these five test cases have no way to pass on OrangeHRM
until fields like this get a locator that actually identifies them.

**Why this wasn't fixed here.** Two separate, non-trivial questions
bundled together — whether `_best_locator()`'s last-resort fallback
should try harder (nearby label text, DOM position, `data-*` attributes)
and whether the crawl needs to expand collapsed search/filter panels
before capturing fields — neither is a quick fix, and this batch was
scoped to the login/session mechanism (D7/D8/D9), not field-locator
quality.

**Status:** open, unowned.
