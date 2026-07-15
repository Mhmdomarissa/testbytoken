# Handoff: Alpha Data Recruitment (ADR) Website Redesign

## Overview
New homepage design for Alpha Data Recruitment, a UAE staffing/recruitment firm. Direction is a premium, credible visual language (inspired by wealth-management site Artorius) built on deep blue backgrounds, a single gold accent, serif/sans type pairing, and full-bleed photography.

## About the Design Files
The HTML file in this bundle (`ADR Website v2.html`) is a **design reference prototype** — built in React + Babel with inline styles, for visual/structural review only. It is not production code. The task is to **recreate this design in the target codebase's existing environment** (React, Next.js, Vue, etc.) using its established component and styling patterns — or, if no environment exists yet, choose the framework best suited to the project and implement there. Do not ship the prototype file itself.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and layout are final/approved. Recreate pixel-perfectly per `DESIGN_LANGUAGE.md`, adapting only to the target codebase's component conventions.

## Screens / Views
Only the **Homepage** is built out so far. It contains, top to bottom:
1. Sticky navigation
2. Hero (full-bleed photo, headline, 2 CTAs)
3. Stats bar (4 stats)
4. About / split section (photo + text, floating stat callout)
5. Service cards (3-column, numbered, photo headers)
6. Industry tiles (4-column, flat)
7. CTA band (full-bleed photo strip)
8. Footer (4-column + bottom bar)

Full layout, component, typography, and color specs for each of these are documented in `DESIGN_LANGUAGE.md` — treat that as the primary spec. Use `ADR Website v2.html` as the structural ground-truth (exact markup/JSX nesting, inline style values) when the Markdown spec is ambiguous.

**Not yet designed:** About Us, Services, Industries, Careers/job-listing pages, and logo. These should extend the same design system (see "Pages in Scope" in `DESIGN_LANGUAGE.md`) once designed.

## Interactions & Behavior
Intentionally minimal:
- Card/tile hover: background lightens (`blue-deep` → `blue-light`), `transition: background-color 0.2s` (industry tiles also transition a bottom border to gold on hover).
- No entrance animations, no parallax, no scroll-triggered effects.
- Nav CTA and hero CTAs are plain links/buttons — no dropdowns or modals in this build.
- No responsive/mobile layout has been designed yet — this is desktop-only. Mobile breakpoints are a follow-up task.

## State Management
None — this is a static marketing homepage with no dynamic data, forms, or client state.

## Design Tokens
See `DESIGN_LANGUAGE.md` for the full token set (colors, type scale, spacing, component specs). Summary:
- **Colors:** `blue-deep #0a1628`, `blue-mid #0d2244`, `blue-light #1a3a6b`, `blue-bright #1e4d8c`, `gold #c9a96e`, `warm-white #f8f4ee`, `muted #8a9ab5`, `footer-deep #060e1b`.
- **Type:** Cormorant Garamond (headings, weight 300, italic for emphasis) + Montserrat (body/UI, weights 300–700). Hero H1 82px/1.05. Full scale in the doc.
- **Spacing:** 1280px max content width, 60px page padding, 80–100px section vertical padding, 8px-based grid.
- **Radius:** 0 everywhere — no rounded corners on any element. This is deliberate.

## Assets
All photography is placeholder stock imagery sourced from Unsplash (Dubai skyline, office/team scenes) — **swap for real client/office photography in production**. No custom icons or illustrations are used; social links in the footer use simple square icon frames (glyphs, not images). No logo file exists yet — the nav currently uses a typographic wordmark placeholder; logo design is a pending follow-up task.

## Files
- `ADR Website v2.html` — homepage prototype (React + Babel, inline styles). Structural/visual reference only.
- `DESIGN_LANGUAGE.md` — full design system spec. Primary reference for recreating the system across new pages.
