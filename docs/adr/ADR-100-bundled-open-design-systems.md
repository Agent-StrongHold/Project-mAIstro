---
id: ADR-100
title: "Bundled and cataloged Open Design design systems for maistro-design"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-14
accepted: 2026-06-14
implemented: 2026-06-14
substrate:
  - maistro-engine#ADR-061
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages/maistro-design/src/maistro_design/systems/importer.py
  - packages/maistro-design/src/maistro_design/systems/bundled/
  - packages/maistro-design/src/maistro_design/systems/catalog/
  - packages/maistro-design/THIRD_PARTY_NOTICES.md
ac-modules:
  AC-1: maistro_design.systems.importer
  AC-2: maistro_design.nodes
  AC-3: maistro_design.systems.importer
  AC-4: maistro_design.systems.importer
  AC-5: maistro_design.systems.importer
  AC-6: maistro_design.systems.importer
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-100 — Bundled and cataloged Open Design design systems

## Context

ADR-061 lists "no bundled design systems — callers must register their own" as
out of scope, leaving `maistro-design`'s `DesignSystemRegistry` empty at install
time. In practice every featured skill (`pitch-deck`, `landing-page`, ...) falls
back to `design_system_slug="default"`, and `DesignOrchestrateNode` constructed
an empty `InMemoryDesignSystemRegistry()` — so `"default"` resolution always
raised `DesignSystemNotFoundError` in the DAG path.

`nexu-io/open-design` (Apache-2.0) ships a `design-systems/` corpus of 150
brand/style packages, each a self-contained `manifest.json` +  `DESIGN.md` +
`tokens.css` + `design-tokens.json` bundle. This is portable data (prose +
CSS custom properties + JSON token exports), not executable code — a good fit
for `DesignSystem.design_md` / `tokens_css` / `colors` / `spacing`.

## Decision

### 1. Two-tier import, both sourced from Open Design's Apache-2.0 corpus

- **Tier-1 (bundled, `TrustTier.T1`)** — 6 systems (`default`, `shadcn`, `apple`,
  `material`, `editorial`, `enterprise`) vendored into
  `systems/bundled/<slug>/`, registered automatically by `load_bundled()`.
  `T1` ("verified/audited third-party") reflects that this content was scanned
  and reviewed at vendoring time, but originates outside the engine (unlike the
  `T0` built-in skills in `skills/builtins.py`).
- **Tier-2 (catalog, `TrustTier.T2`)** — the remaining 144 systems vendored into
  `systems/catalog/<slug>/`, indexed by `systems/catalog/catalog.json`
  (slug, name, category, license, source commit, `scan_status`). One-click
  import via `import_from_catalog(slug, registry)`, registered at `T2`
  ("community/unaudited") — consistent with the existing `DesignSystemLoader`
  default for caller-registered systems.

### 2. A repeatable content scan gates both tiers

`scan_design_system_content()` checks each system's four essential files for:
script/eval/iframe injection, prompt-injection phrasing, large base64 blobs,
Unicode steganography (zero-width/format/control characters via
`unicodedata.category`), and external URLs against a small documentation/font-CDN
allowlist (non-blocking — recorded as `external_urls`). All 150 vendored systems
pass with `scan_status: "clean"`. `import_from_catalog()` re-runs the scan at
import time (defense-in-depth on top of the vendoring-time scan recorded in
`catalog.json`), raising `TrustBannedError` if a system no longer passes.

### 3. `import_open_design_system()` bridges Open Design's real manifest shape

Open Design's `manifest.json` (schema `od-design-system-project/v1`) is keyed by
`id` with nested `files`/`craft`/`preview`/`sourceFiles` — distinct from
`DesignSystemLoader.from_dict()`'s flat shape. `import_open_design_system()`
reads `id`/`name`/`description`/`category` directly, preserves `DESIGN.md` as
`design_md` and `tokens.css` as `tokens_css` verbatim, and projects
`design-tokens.json`'s flat token array into `ColorToken` (type `"color"`) and
`SpacingToken` (`--space-*` dimension tokens) — leaving `DesignSystemLoader`
unchanged for its existing flat-manifest callers.

### 4. `DesignOrchestrateNode` now resolves `"default"`

`nodes.py` calls `load_bundled(system_registry)` alongside the existing
`load_builtins(skill_registry)`, so `design.orchestrate`'s default
`design_system_slug="default"` resolves without callers registering anything.

## Acceptance criteria

```gherkin
@AC-1
Scenario: load_bundled registers all Tier-1 slugs at T1
  Given an empty DesignSystemRegistry
  When load_bundled(registry) is called
  Then registry.get(slug) is not None for every slug in BUNDLED_SLUGS
  And each has trust_tier == T1, non-empty design_md and tokens_css

@AC-2
Scenario: "default" is resolvable by DesignOrchestrateNode
  Given DesignOrchestrateNode._execute with design_system_slug="default" (the field default)
  When the node runs
  Then it returns a result for design_system_slug == "default" (no DesignSystemNotFoundError)

@AC-3
Scenario: one-click catalog import registers at T2
  Given a slug present in catalog.json with scan_status == "clean"
  When import_from_catalog(slug, registry) is called
  Then registry.get(slug) is not None and trust_tier == T2

@AC-4
Scenario: catalog import re-scan blocks banished content
  Given a banish list containing a pattern present in a catalog system's files
  When import_from_catalog(slug, registry, banish_list=banish_list) is called
  Then TrustBannedError is raised and the system is not registered

@AC-5
Scenario: scan flags injection content as not passed
  Given file content containing "<script>" or "ignore previous instructions"
  When scan_design_system_content(files) is called
  Then report.passed is False and the matched pattern appears in blocking_flags

@AC-6
Scenario: every catalog entry is Apache-2.0 and clean
  Given catalog.json
  Then every entry has license == "Apache-2.0" and scan_status == "clean"
```

## Consequences

**Positive:**
- Featured skills work out of the box without callers registering a design system.
- A vetted, labeled (T1/T2, scan status, license, source commit) on-ramp to
  Open Design's full 150-system corpus, addressing the security-review bar for
  importing third-party design content.
- `import_open_design_system()` is reusable for future Open Design syncs or for
  importing additional systems beyond the initial 150.

**Negative:**
- ~5.8MB of vendored content ships with `maistro-design` (4 files x 150 systems).
- The scan is a heuristic pre-check, not a substitute for Warden's full pipeline;
  `import_from_catalog()`'s re-scan and the `T1`/`T2` tiering are the mitigations
  (per ADR-061 §3, trust only decreases from there).
- Re-syncing from upstream Open Design requires re-running the vendoring scan and
  regenerating `catalog.json` (no automated sync job in this ADR).

## Out of scope

- Automated re-sync / update pipeline from `nexu-io/open-design`.
- Admin UI for browsing or one-click-importing from the catalog (catalog.json +
  `import_from_catalog()` are the API; UI is a caller concern).
- Vendoring Open Design's `components.html`, `preview/`, `source/`, `USAGE.md`,
  or `tailwind-v4.css` — only the four files that feed `DesignSystem` are kept.
- Vendoring Open Design *skills* (as opposed to design systems).
