# Conductor design system — as-is extraction

**Status:** audit, not a decision record (no registry front matter on purpose)
**Decision it feeds:** [ADR-091626-ba4f](../adr/ADR-091626-ba4f-workspace-design-system-first-party-bundle.md) — the Workspace design system
**Measured against:** `packages/hive-conductor/frontend/src/{index.css,App.css,themes/dark.css,fantasia-theme.css}` at `b542ef5`, 2026-09-16
**Successor:** `packages/maistro-design/src/maistro_design/systems/bundled/workspace/` (`DESIGN.md`, `tokens.css`, `components.html`, `preview/home.html`)

## Why this document exists

The Workspace cutover plan says the Conductor's flaws are in its seams, not its pages.
The stylesheet is one of those seams: there is no design system, only a stylesheet that
grew. Before replacing it, this records what is actually there, with numbers, so that
the replacement's targets are measured against a baseline and not against a feeling.

## What exists today

| Measure | index.css | Notes |
|---|---|---|
| Classes | 113 | One file; no component boundaries |
| Distinct `font-size` values | 18 (30 across the four stylesheets) | 8px, 9px and 10px each appear; `0.63rem` on the status pill |
| Smallest text | 8px | `.stat-card .label`, `.table th`, `.hex-badge`, `.mobile-user-bar` (640px) |
| `!important` rules | 56 | Mostly in `.workspace-toolbar`/share/tool-bindings panels, fighting earlier auto-generated `button` rules the file's own comments describe |
| Accent variables | 9 | `--accent`, `--accent-2`, `--accent-gradient`, `--accent-hover`, `--accent-light`, `--honey`, `--honey-dark`, `--honey-light`, `--purple` — four hues where the narrative asks for one |
| Raw hex outside `:root` | 14 | Hex-badge tints, hover borders, gradient stops |
| Hover `translateY(-1px)` lifts | 11 | Every card, button and prompt lifts on hover; nothing is still |
| Theme files | 3 (814 lines in dark + fantasia) | Each rebinds the same variables by hand and then patches components by selector |
| Font stacks | `--sans`, `--mono`, `--hand` (alias of sans) | Inter Variable and JetBrains Mono ship from the app's origin (FONTS.md) |
| Pages | 29 | Per the cutover plan, all are listed for parity-then-delete |
| Raw `fetch(` outside `lib/api` | 66 | Cutover plan P0.3 |

### Tokens as declared (light)

```
--paper #fafafa   --paper-2 #f5f5f5   --ink #1a1a1a   --pencil #6b7280   --rule rgba(0,0,0,.08)
--accent #2563eb  --accent-2 #7c3aed  --accent-gradient 135deg #2563eb → #4f46e5
--honey #2563eb   --honey-dark #1d4ed8 (honey is a renamed accent)   --purple #7c3aed
--danger #dc2626  --ok #16a34a  --warn #d97706
--shadow-xs/sm/md/lg (layered)  --shadow-accent (blue glow)  --ease cubic-bezier(.4,0,.2,1)
```

Dark and Fantasia both rebind these to deep indigo (`#0c0a1a`) with a violet accent
(`#a78bfa`) and a gold secondary (`#fbbf24`), then override `.card`, `button`,
`input`, the sidebar and the scrollbar by selector. Fantasia adds a starfield on
`.main-content`.

### Components as they exist

- **Buttons.** A baseline `button {}` (13px sans, 8px radius, shadow, lift on hover);
  `.btn` (10px mono, 1.3px ink border); `.btn-accent`, `.btn-primary` (gradient + glow);
  `.btn-model`, `.btn-icon`, `.send-btn`, `.prompt-btn`, `.ghostbtn`. Eight button
  idioms, four sizes, three radii.
- **Badges.** `.hex-badge` — 8px uppercase mono in a hexagon clip-path, five colour
  variants; `.dashboard-status-pill` — 0.63rem with a pulsing dot animation.
- **Cards.** `.card` (14px radius), `.stat-card` (10px), `.widget-card` (10px),
  `.dashboard-widget-card`; all lift and glow on hover.
- **Tables.** `.table` at 9px mono with 8px uppercase headers.
- **Inputs.** `.input-field` at 10px mono with an ink border; `.chat-textarea` at 14px
  sans; panel inputs at 12px.
- **Workspace switcher.** `.workspace-tab` buttons, 12px, styled with `!important`
  to outrank the button baseline; share/tools/persona panels each restyle every
  button inside them.
- **State handling.** Loading is a boolean per widget; empty is a sentence
  ("No invocations yet"); errors and permission denials share the empty face.
  No skeleton, no last-seen, no "what's missing".
- **Provenance.** None. The audit log is a page (`AuditLog.tsx`); actors are not
  colour-coded; there is no why, no undo, no age on a wait.

## What the narrative asks for, and the baseline each target replaces

| Target (from the Workspace narrative and prototypes) | Baseline today |
|---|---|
| 12px floor, nothing smaller | 8px labels, 9px table body, 10px buttons and inputs |
| One accent; blue means you | Four accent hues plus a gradient; blue is decoration |
| Four actor colours, fixed | No actor colour; audit rows are plain text |
| Every wait carries its age | Approvals and blocked goals have no timestamp in the UI |
| Cited why-panel on every agent and gate action | No why anywhere |
| Three honest undo outcomes | No undo |
| Four state faces, never swapped | Loading and error share the empty face |
| Switcher in at most six Tab presses | Toolbar with 51 focus stops before the switcher |
| Nothing animates unprompted | 11 hover lifts, a pulsing status dot, a starfield |
| Two typefaces, one reading, one machine | Three variables, mono used for labels, buttons and tables |
| Persona = field, bloom, accent (four values) | Persona theme = a 250–550 line CSS file per theme |

## What the successor keeps

- Shipping typefaces from the app's own origin (FONTS.md). Bricolage Grotesque joins
  JetBrains Mono; Inter is retired for the Workspace surface.
- Layered, soft elevation rather than hard drop shadows — but on raised panels only,
  not on every card.
- `data-theme` on `<html>` as the switching mechanism (`lib/appearance.ts`,
  `WorkspaceContext`), extended with `data-scheme` for light/dark so a persona's
  theme and the user's scheme choice stop fighting over one attribute.
- The Fantasia idea — a workspace that feels like a place — as the bloom behind
  the glass, without the starfield or the violet/gold palette.

## What the successor drops

- `--honey`, `--purple`, `--accent-2`, `--accent-gradient`, `--shadow-accent`.
- Every `!important`.
- Mono for anything that is not an id, hash, key=value or seq number.
- Uppercase tracked labels, hexagon badges, hover lifts.
- Per-theme component overrides: a persona rebinds tokens and nothing else.
