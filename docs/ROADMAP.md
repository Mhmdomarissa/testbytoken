# Product Roadmap — self-serve TaaS through Rung 4

> **Strategic frame (decided 2026-07-16).** This product is the acquisition
> funnel for the existing testing business. Self-serve customers discover us
> through a zero-friction public proof, grow through staging and Git/cloud
> integration, and the largest of them convert into enterprise agreements.
> Anything past Rung 4 — internal applications with high security
> restrictions, special hardware/software setups — is handled by the
> **conventional onsite model we already operate**, not by this product.
> The roadmap below therefore ends at Rung 4 by design.

## The core utilization we are building toward

A team developing an application **invites us into their Git and cloud
infrastructure** and runs tests inside their **dev and test environments
right through to production**. The product's job is to make each step of
that invitation small, revocable, and obviously worth it — the proof
artifact does the selling at every rung.

**Environment progression principle:** the same plain-English test suite is
promoted across environments. Full journeys (including writes and logins)
run in dev/test; **production runs are read-only** — that keeps the existing
hard rule intact and makes production monitoring safe to sell.

---

## Phase 0 — Ship the demo safely (prerequisite, in progress)

Everything below assumes a publicly reachable service, so the critical items
in `bug_fixes.md` gate this phase: XSS from tested sites, run-ID collisions,
guardrail hardening, rate limiting. Plus the remaining README tasks: SSE
streaming, signup wall after the proof screen, single-container deploy with
`TAAS_LOCAL_DEMO=0`.

**Exit:** a stranger can paste a URL, watch a run, see the proof, and leave
an email address — without being able to hurt us or anyone else.

## Phase 1 — Rung 1: public-URL proofs as a product

**Customer:** anyone with a public site; marketers, founders, agencies.
**Access:** none needed — public URLs only, read-only checks.

Build:
- Accounts + test-token billing (the token metering already exists per run).
- **Scheduled monitoring**: recurring runs with a proof history — a
  hash-linked chain of evidence over time, not just a green/red dot.
- Proof permalinks / shareable proof pages (each shared proof is marketing).
- Use-case packaging: pre-launch checks, compliance evidence (cookie banner,
  disclosures, headers present).

**Exit:** first paying subscriptions; proofs being shared outside the
customer's own team.

## Phase 2 — Rungs 2–3: behind the front door with revocable secrets

**Customer:** teams and agencies with staging/UAT sites.
**Access:** a shared secret we inject (`Authorization: Basic …` or a custom
header like `X-Proof-Token`) and/or **published static egress IPs** the
customer allowlists. Deliberately *not* user credentials — revocable,
low-stakes, minutes to set up.

Build:
- Per-target secret storage (encrypted at rest; this is the gentle warm-up
  for the vault, per `docs/CREDENTIALS.md` patterns — secrets are write-only
  through the UI, never echoed back).
- Header/basic-auth injection in the runner; static egress IP documentation.
- Target ownership verification (DNS TXT record or meta tag) before we agree
  to hammer a non-public host.
- Agency packaging: **handover proofs** — a signed proof bundle delivered
  with a finished site.

**Exit:** customers running suites against staging before releases; first
agency using proofs in client deliveries.

## Phase 3 — The Git/cloud invitation (the growth engine)

**Customer:** software teams; this is the core utilization.
**Access:** they install our **GitHub App** (GitLab later) and point us at
their cloud preview/dev/test environments.

Build:
- GitHub App + Action: on every PR, run the suite against the preview/dev
  deployment URL and post the proof back to the PR as a check + comment.
- Environment model in the product: one suite, multiple targets
  (dev → test → staging → prod), with per-environment access config from
  Phase 2 and per-environment run history.
- Team features: shared suites, roles, org billing — this is where a
  single user becomes a team account.

Every PR proof is seen by the whole team; this rung is the viral loop and
the on-ramp to larger contracts.

**Exit:** proofs appearing on PRs in customer repos; team accounts growing
seat counts organically.

## Phase 4 — Rung 4: authenticated journeys (credentials vault, done properly)

**Customer:** teams whose value lives behind a login — dashboards, checkout,
member areas. The biggest testable market and the headline paid feature.
**Access:** a real credentials vault holding **dedicated test accounts only**
(never real-user credentials), built to the `docs/CREDENTIALS.md` pattern
with actual crypto — this phase is where the stub becomes real.

Build:
- Vault: envelope encryption, write-only credentials, per-run ephemeral
  injection into the disposable browser context, audit log of every access.
- Login step types in the runner (form login first; SSO/OAuth test flows
  later), session handling within the one-context-per-run rule.
- Write-path tests allowed in dev/test environments; production stays
  read-only-after-login (view dashboards, verify content — no mutations).

**Exit:** authenticated end-to-end journeys (signup → dashboard → checkout
short of payment) running on schedules and in CI.

---

## The enterprise handoff (the boundary of this product)

When a customer needs testing of **internal applications with high security
restrictions**, air-gapped or regulated environments, or special
hardware/software setups, the product's job is to *recognize the signal and
hand off* — not to build for it. That work transfers to the conventional
model with onsite testers (and the UTS Global Test Magic engine direction
lives on that side of the line).

Handoff signals to watch for in-product: requests for VPN/agent access,
private-network targets hitting the guardrail, procurement/security
questionnaires, seat counts or run volumes crossing enterprise thresholds.
Route these to sales, with the customer's proof history as the account
context.

## Sequencing logic (why this order)

1. Each phase monetizes before the next one is needed: Phase 1 sells what is
   already built; Phase 2 is days of work, not months; Phase 3 reuses
   Phase 2's access plumbing; Phase 4 is the only heavy security build and
   arrives once trust and revenue justify it.
2. Trust escalates in revocable steps: no secret → staging secret → repo
   permission → test-account credentials. We never ask for more than the
   value already demonstrated.
3. The engine stays swappable throughout (per README) — nothing here deepens
   API coupling to `runner.py`, so the UTS decision remains free.
