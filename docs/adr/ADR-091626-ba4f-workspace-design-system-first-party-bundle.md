---
id: ADR-091626-ba4f
title: "The Workspace design system is a first-party bundled Open Design system"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-16
accepted: 2026-09-16
substrate:
  - maistro-engine#ADR-061
  - maistro-engine#ADR-100
  - maistro-engine#ADR-081226-e626
implements: []
related:
  - maistro-engine#ADR-062326-616c
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-design/tests/test_workspace_system.py
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-16
  - status: Accepted
    date: 2026-09-16
---

# ADR-091626-ba4f: The Workspace design system is a first-party bundled Open Design system

## Context

The Workspace (#1046, #1048, #65) is the fourth attempt at a product surface. The
Conductor UI it replaces has no design system: `index.css` carries 113 classes and, with its three theme files, 30
distinct font sizes (8px table headers, 9px table body, 10px buttons), four competing
accents (`--accent`, `--honey`, `--purple`, a gradient), 56 `!important` rules, and
three theme files (`index.css`, `themes/dark.css`, `fantasia-theme.css`) that each
redefine the same variables by hand. The as-is extraction is in
`docs/product/CONDUCTOR-DESIGN-SYSTEM-AUDIT.md`.

The Workspace narrative and the two legibility prototypes (`agent-legibility.html`,
`workspace-wireframe.html`) already fix the grammar the new surface needs: four actor
colours for "who decided this", ages on every wait, cited why-panels, three honest
undo outcomes, four state faces that never wear each other's face, a 12px floor, and
the workspace switcher within six Tab presses. What was missing was a place for that
grammar to live as tokens a renderer, an agent and a human can all read.

`maistro-design` already has that place. ADR-100 bundles Open Design systems as
`manifest.json` + `DESIGN.md` + `tokens.css` + `design-tokens.json`, loads them at
`TrustTier.T1`, scans them for injection, and feeds `DESIGN.md` and the colour tokens
into every generation prompt. Persona (ADR-081226-e626) is configuration that carries
"voice, tone, style, and theme" and never authority, so a persona's theme is a natural
consumer of a design system's token contract.

## Decision

### 1. `workspace` is a Tier-1 bundled design system, authored here

`packages/maistro-design/src/maistro_design/systems/bundled/workspace/` ships the four
essential files plus a static `components.html` kit and `preview/home.html`. It is
added to `BUNDLED_SLUGS`, indexed in `catalog.json` with `tier: bundled` and a
first-party `source`, and recorded in `THIRD_PARTY_NOTICES.md` as the one bundled
system not vendored from open-design. The same loader, scan and prompt-stack assembly
apply; nothing in `maistro_design` special-cases it.

### 2. It shares the Open Design token schema and extends it

`tokens.css` declares every standard token (`--bg`, `--surface`, `--fg`, `--muted`,
`--border`, `--accent`, `--success`, `--warn`, `--danger`, fonts, type scale, spacing,
radius, elevation, focus, motion, layout) so a component written for `default`
resolves unchanged. It adds the Workspace vocabulary: glass surfaces over a bloom,
`--actor-{human,agent,gate,system}`, `--face-{loading,empty,error,denied}-*`,
`--undo-{ok,partial,logged}-*`, `--age-*`, `--ledger-*`, the type registers and
`--text-floor: 12px`.

### 3. Meaning is fixed; taste belongs to the persona

The actor quartet, the state faces, the type floor, the focus ring and the fonts are
declared once in `:root` and may not be rebound by a persona. A persona template
(`greenhouse` — the default — `slate`, `studio`) rebinds only `--bg`, `--surface`,
`--bloom`, `--accent`, `--accent-on`; a user-authored theme supplies the same values
per scheme and is rejected under 4.5:1 for `--accent-on` on `--accent` or `--accent`
on `--bg`. `manifest.json#personas` enumerates the customisable and fixed sets so the
persona editor can read them rather than duplicate them.

### 4. The Conductor consumes it; it does not fork it

The Workspace surfaces built under #1048 bind to this `tokens.css` through
`data-theme` / `data-scheme` on `<html>`, replacing the three hand-maintained theme
files. Bricolage Grotesque joins JetBrains Mono in `FONTS.md` as a shipped, versioned
typeface (`@fontsource-variable/bricolage-grotesque`). That wiring is a separate
change under the Workspace cutover plan ("contract before surface"); this ADR fixes
the contract.

## Acceptance criteria

```gherkin
@AC-1
Scenario: workspace is bundled at T1 like the other Tier-1 systems
  Given an empty DesignSystemRegistry
  When load_bundled(registry) is called
  Then registry.get("workspace") is not None, trust_tier == T1, metadata.origin == "bundled"
  And its design_md and tokens_css are non-empty and it exports more than 20 colour tokens

@AC-2
Scenario: the catalog index and manifest record first-party provenance
  Given catalog.json and bundled/workspace/manifest.json
  Then the catalog entry has tier == "bundled", trust_tier == "t1", license == "Apache-2.0"
  And source.repo == "Agent-StrongHold/Project-mAIstro" and manifest.source.type == "first-party"

@AC-3
Scenario: the essential files pass the import-time content scan
  Given manifest.json, DESIGN.md, tokens.css and design-tokens.json
  When scan_design_system_content(files) is called
  Then report.passed is True and report.external_urls is empty

@AC-4
Scenario: the grammar is in the tokens
  Given tokens.css
  Then :root declares --actor-human/agent/gate/system, the four --face-* tokens,
       the three --undo-* tokens, --text-floor: 12px, and no --text-* size below 12px

@AC-5
Scenario: a persona template rebinds only what a persona may
  Given the slate and studio blocks (light and dark)
  Then every token they declare is one of --bg, --surface, --bloom, --accent, --accent-on
  And the dark scheme rebinds the actor quartet's lightness but not --text-floor or --focus-ring

@AC-6
Scenario: design-tokens.json mirrors :root and the previews are static
  Given design-tokens.json, components.html and preview/home.html
  Then the exported token names equal the names declared in :root
  And neither preview contains a script element or a URL outside the font hosts
```

## Consequences

### Positive
- The Workspace surface has one token contract that the renderer, the design engine's
  prompt stack and the persona editor all read.
- "Who decided this" is a colour rule an agent generating UI cannot accidentally
  break: the quartet is in the tokens and tested.
- Adding a persona theme is four values per scheme, and the contrast gate is stated.

### Negative / Trade-offs
- `maistro-design` now carries one system whose provenance is not open-design; the
  notices file and `manifest.source.type` carry that distinction, and the importer
  docstring names the exception.
- A new variable typeface (Bricolage Grotesque) must be shipped from the Conductor's
  origin before the surface can use it offline.

### Neutral
- ADR-100's "6 systems" count becomes 7; ADR-100 is unchanged as a historical record.
- The previews drive persona and scheme with CSS `:has()` on radio inputs so they
  ship without scripts; browsers older than 2023 show the default persona only.
