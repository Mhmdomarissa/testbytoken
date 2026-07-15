# Alpha Data Recruitment — Design Language

This document defines the visual design system for the Alpha Data Recruitment (ADR) website and app rebuild. It was distilled from an approved HTML prototype (`ADR Website v2.html` in this bundle — reference it directly for exact markup/structure of the homepage).

**How to use this doc:** Recreate this design system in the target codebase's existing framework (React, Vue, Next.js, etc.) using its own component patterns — this is a style reference, not code to copy verbatim, though the prototype's JSX structure is a faithful guide to layout. If no framework exists yet, choose the best fit for the project.

## Brand Positioning
Alpha Data Recruitment brings humanity back to outsourcing and staffing — every outsourced employee is hired and treated as an internal hire. Tone is **corporate and credible**: numbers-led, formal, trustworthy. The visual language borrows the restraint and elegance of premium wealth-management sites (Artorius was the stylistic reference) but adapted to a UAE staffing/recruitment context.

---

## Color Palette

Deep, saturated blue as the dominant background, with warm gold as the single accent color. No other hues are used.

| Token | Hex | Usage |
|---|---|---|
| `blue-deep` | `#0a1628` | Page background, nav, footer base, service section bg |
| `blue-mid` | `#0d2244` | Section alternation bg (About text panel, Industries section) |
| `blue-light` | `#1a3a6b` | Hover state for cards/tiles |
| `blue-bright` | `#1e4d8c` | Stats bar background, floating stat-card accents |
| `gold` | `#c9a96e` | Accent color — CTAs, headlines emphasis, dividers, labels, links |
| `warm-white` | `#f8f4ee` | Primary text on dark backgrounds |
| `muted` | `#8a9ab5` | Secondary text, blue-tinted gray |
| `footer-deep` | `#060e1b` | Footer background (darkest) |

Text on dark background uses `rgba(248,244,238, opacity)` at varying opacities (0.22–0.75) for hierarchy instead of separate gray tokens — prefer this pattern over introducing new grays.

**Do not add new hues.** If a new state color is needed (error, success), derive it with OKLCH from the existing gold/blue rather than introducing an unrelated color.

---

## Typography

Two-font pairing throughout:

- **Headings:** `Cormorant Garamond` (serif), weight 300 (light), italic used selectively for emphasis phrases within a headline (rendered in gold). Letter-spacing slightly negative (`-0.02em` to `-0.01em`) at large sizes.
- **Body / UI:** `Montserrat`, weights 300–700. All-caps labels/eyebrows/buttons use Montserrat 600–700 with wide letter-spacing (`0.14em`–`0.26em`).

Google Fonts import:
```html
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@200;300;400;500;600;700&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap" rel="stylesheet">
```

### Type Scale
| Role | Font | Size | Weight | Notes |
|---|---|---|---|---|
| Hero H1 | Cormorant Garamond | 82px | 300 | line-height 1.05, max-width ~780px |
| Section H2 | Cormorant Garamond | 50–52px | 300 | line-height 1.15–1.2 |
| Card / subsection H3 | Montserrat | 20px | 600 | |
| Stat number | Cormorant Garamond | 44–58px | 300 | gold color |
| Eyebrow label | Montserrat | 10–11px | 600 | uppercase, letter-spacing 0.22–0.26em, gold |
| Nav link | Montserrat | 11px | 500 | uppercase, letter-spacing 0.15em |
| Body paragraph | Montserrat | 14–16px | 300–400 | line-height 1.8–1.9 |
| Button label | Montserrat | 11–12px | 600–700 | uppercase, letter-spacing 0.16em |

---

## Spacing & Layout

- Max content width: **1280px**, centered, with **60px** horizontal page padding (desktop).
- Section vertical padding: **80–100px** top/bottom for standard sections; hero is a fixed **700px** height.
- Grid-based two-column sections (About) split **50/50**, no gap — panels touch edge-to-edge (photo full-bleed against solid-color text panel).
- Card grids (Services, Industries) use `gap: 2px` with a bg color showing through as a hairline divider, not conventional 16–24px gutters — this is a deliberate "seamed panel" look distinct from typical card-with-shadow patterns.
- Buttons: pill-free, sharp rectangular corners, generous horizontal padding (36–52px), no border-radius anywhere in this system. **Border-radius is 0 throughout** — this is a deliberate, distinguishing choice (no rounded corners on cards, buttons, or images).

---

## Components

### Navigation
Sticky top nav, `76px` tall, `blue-deep` background, bottom hairline border (`1px solid rgba(255,255,255,0.07)`). Logo is two-line stacked wordmark (brand name gold, subtitle line muted, uppercase, tight tracking). Right-aligned ghost button with gold border for primary CTA ("Get in Touch").

### Hero
Full-bleed photographic background image with a directional gradient overlay (dark from one side fading to transparent) so headline text sits on a readable dark zone while photo remains visible. Small gold divider-line + eyebrow label precedes the H1. H1 uses a 3-line break pattern with one line in gold italic for emphasis. Two CTAs: solid gold primary + outlined ghost secondary.

### Stats bar
Full-width band in `blue-bright`, 4 stats centered horizontally, separated by thin vertical hairlines (`rgba(255,255,255,0.15)`). Each stat: large Cormorant Garamond gold number + small uppercase muted label below.

### About / split section
50/50 grid: photo panel (with an absolutely-positioned "floating" stat callout card overlapping its bottom-right corner, gold left-border accent) + solid-color text panel with eyebrow, headline (partial italic gold emphasis), two paragraphs, and a gold text link with arrow.

### Service cards
3-column grid, `gold`-hairline-seamed. Each card: photo header (200px, darkened overlay, index number "01/02/03" top-left in gold italic serif) → padded body with a short gold divider line, H3 title, description paragraph. Hover: card background lightens to `blue-light`.

### Industry tiles
4-column grid of flat tiles (no photos), each with a short gold divider line, bold title, and a muted one-line description. Hover: background lightens, bottom border becomes gold.

### CTA band
Full-bleed photo strip (~360px tall) with a strong horizontal gradient overlay, headline + supporting text on the readable side, solid gold button on the transparent/photo side.

### Footer
Darkest background (`#060e1b`). 4-column grid: brand block (wordmark + one-line description + square icon-frame social links) + 3 link columns with gold uppercase headings and muted links. Bottom bar: copyright + legal links, all at lowest opacity (~0.22).

---

## Imagery

Photography is essential to this system — it is not a decorative afterthought. Required photo slots per page: hero (skyline/cityscape, dusk/dramatic lighting), about (team/office, warm and professional), 3× service card photos (professional/workplace scenes), CTA band (office/skyline). All photos get a dark blue overlay wash (`rgba(10,22,40, 0.35–0.6)`) when text sits on top, never used at full brightness under text. Treat this as **the** signature move of the design — swap in real client/office photography here, not stock filler, when moving to production.

---

## Motion / Interaction

Minimal, functional only: background-color transitions on hover (`transition: all 0.2s` / `background-color 0.2s`) for cards and tiles. No entrance animations, no parallax. Keep it restrained — this is a premium-credible register, not a flashy one.

---

## Voice & Copy Patterns

- Headlines: short, declarative, broken across 2–3 lines, with one phrase set in italic gold for emphasis (e.g. "The people who *drive your business* forward.")
- Eyebrow labels: all-caps, 2–4 words, framed by gold divider lines (e.g. "— OUR PHILOSOPHY —")
- Body copy: confident, numbers-led ("700+ professionals", "20+ years"), always ties back to the core message that ADR treats outsourced staff as internal hires.
- CTAs: imperative, short — "Find Talent", "Browse Roles", "Get in Touch", "Discover our story →"

---

## Pages in Scope (from prototype)
Currently built: **Homepage** only. Planned next: About Us, Services, Industries, Careers/Job listings — each should extend this same system (section-band rhythm of blue-deep/blue-mid alternation, gold accents, Cormorant/Montserrat pairing, full-bleed photography).

## Files in This Bundle
- `ADR Website v2.html` — working prototype implementing this system (React + Babel, inline styles). Use as the structural/visual reference for the homepage; do not ship this file itself to production.
