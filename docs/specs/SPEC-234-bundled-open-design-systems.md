---
id: SPEC-234
title: "Bundled and cataloged Open Design systems for maistro-design"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-100
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-design/tests/test_importer.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-234: Bundled and cataloged Open Design systems

## Context

ADR-100 decided to vendor Open Design's (Apache-2.0) `design-systems/` corpus into
`maistro-design` as a two-tier import: 6 bundled Tier-1 (`T1`) systems registered
automatically, and a 144-system Tier-2 (`T2`) catalog with one-click import, both
gated by a content scan. This closes the gap where `DesignOrchestrateNode`'s default
`design_system_slug="default"` previously always raised
`DesignSystemNotFoundError`. This is implemented and tested; this SPEC documents the
shipped module.

## Goals

- Document the actual importer functions, bundled slugs, catalog shape, and trust-tier
  model as coded.
- Map ADR-100's Gherkin acceptance scenarios to real tests.
- Confirm `DesignOrchestrateNode` actually resolves `"default"` now.

## Non-goals

- An automated re-sync/update pipeline from `nexu-io/open-design`.
- An admin UI for browsing/importing from the catalog.
- Vendoring Open Design's non-design-system assets (`components.html`, `preview/`,
  `source/`, `USAGE.md`, `tailwind-v4.css`) or Open Design *skills*.

## Decision

`packages/maistro-design/src/maistro_design/systems/importer.py`:

```python
def load_bundled(registry: DesignSystemRegistry) -> None: ...
def import_from_catalog(
    slug: str, registry: DesignSystemRegistry, *,
    trust_tier: TrustTier = TrustTier.T2,
    banish_list: InMemoryTrustBanishList | None = None,
) -> DesignSystem: ...
def import_open_design_system(
    manifest: dict[str, Any], *, design_md: str = "", tokens_css: str = "",
    design_tokens: dict[str, Any] | None = None,
    trust_tier: TrustTier = TrustTier.T2,
) -> DesignSystem: ...
def scan_design_system_content(
    files: dict[str, str], *,
    banish_list: InMemoryTrustBanishList | None = None,
    url_allowlist: tuple[str, ...] = DEFAULT_URL_ALLOWLIST,
) -> ScanReport: ...
# Also present (not enumerated in the ADR text):
def load_catalog() -> list[dict[str, Any]]: ...
```

Tier-1 bundled systems, `systems/bundled/{apple,default,editorial,enterprise,material,shadcn}/`,
matching `BUNDLED_SLUGS = ("default", "shadcn", "apple", "material", "editorial", "enterprise")`.

Tier-2 catalog: `systems/catalog/catalog.json`, 150 entries (the ADR's text says 144;
the file as it ships has 150), each with `slug`, `name`, `category`, `description`,
`tier` (`"catalog"`), `trust_tier` (`"t2"`), `license` (`"Apache-2.0"`),
`source` (`repo`, `path`, `ref`), `scan_status` (`"clean"`), `scan_external_urls`.

`TrustTier` is defined in `packages/maistro-design/src/maistro_design/trust.py`
(`StrEnum`): `T0` (built-in/immutable), `T1` (verified/audited), `T2`
(community/unaudited), `T3` (untrusted/runtime), `SKULL` (banished), with a `.min()`
method enforcing trust only decreases.

`packages/maistro-design/src/maistro_design/nodes.py` imports `load_bundled` (line 18)
and calls it (line 74) when constructing the node's `InMemoryDesignSystemRegistry()`,
so `design.orchestrate`'s default `design_system_slug="default"` now resolves.

## Acceptance criteria

- [x] `load_bundled(registry)` registers all `BUNDLED_SLUGS` at `TrustTier.T1` with non-empty `design_md`/`tokens_css`
- [x] `DesignOrchestrateNode` resolves `design_system_slug="default"` without raising `DesignSystemNotFoundError`
- [x] `import_from_catalog(slug, registry)` registers a clean catalog system at `TrustTier.T2`
- [x] `import_from_catalog(..., banish_list=...)` raises `TrustBannedError` and does not register when content matches the banish list
- [x] `scan_design_system_content()` flags `<script>`/prompt-injection/base64-blob/zero-width-character content as not passed
- [x] Every catalog entry has `license == "Apache-2.0"` and `scan_status == "clean"`

## Testing

`packages/maistro-design/tests/test_importer.py`:
- `TestLoadBundled::test_load_bundled_registers_all_bundled_slugs`
- `TestLoadBundled::test_default_design_system_is_bundled`
- `TestCatalog::test_import_from_catalog_registers_at_t2`
- `TestImportOpenDesignSystem` (class) / `test_banish_list_match_is_blocking` (in `TestScanDesignSystemContent`)
- `TestScanDesignSystemContent::test_script_tag_is_blocking`
- `TestScanDesignSystemContent::test_prompt_injection_phrase_is_blocking`
- `TestScanDesignSystemContent::test_large_base64_blob_is_blocking`
- `TestScanDesignSystemContent::test_zero_width_character_is_blocking`
- `TestCatalog::test_all_catalog_entries_are_clean`
- `TestCatalog::test_catalog_apache_licensed`
- `TestDesignOrchestrateNodeBundling` (class) — covers the node/bundling integration directly

## Open questions

- ADR-100 text states 144 catalog entries; the shipped `catalog.json` has 150 — worth
  a one-line correction to the ADR's count (not a code change, no functional gap).
- No automated re-sync job exists for pulling updates from `nexu-io/open-design`; if
  upstream design systems change, the catalog and scan results go stale until someone
  manually re-vendors and reruns the scan.

## References

- `packages/maistro-design/src/maistro_design/systems/importer.py`
- `packages/maistro-design/src/maistro_design/systems/bundled/`
- `packages/maistro-design/src/maistro_design/systems/catalog/catalog.json`
- `packages/maistro-design/src/maistro_design/trust.py`
- `packages/maistro-design/src/maistro_design/nodes.py`
- `packages/maistro-design/tests/test_importer.py`
- `packages/maistro-design/THIRD_PARTY_NOTICES.md`
