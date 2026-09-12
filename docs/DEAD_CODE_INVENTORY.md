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
