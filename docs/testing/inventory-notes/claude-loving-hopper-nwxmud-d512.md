---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-design/tests: +14
---
# Workspace design system bundle (ADR-091626-ba4f, #1046)

Sixteen new collected cases, all from adding `workspace` as the seventh Tier-1
bundled design system in `maistro-design`:

- `packages/maistro-design/tests/test_workspace_system.py` (+14) — the ADR's six
  criteria, each bound with `@pytest.mark.ac("ADR-091626-ba4f/AC-N")`: bundled at
  T1 with `origin == "bundled"`; catalog entry and manifest record first-party
  provenance; the four essential files pass the import-time content scan; `:root`
  declares the actor quartet, the four state faces, the three undo outcomes and a
  12px floor with no `--text-*` size below it; the slate and studio persona blocks
  rebind only `--bg/--surface/--bloom/--accent/--accent-on` and the dark scheme
  leaves `--text-floor` and `--focus-ring` alone; `design-tokens.json` mirrors
  `:root` and both previews carry no script and no URL outside the font hosts.
  After the Codex review, five more: the contrast claims DESIGN.md makes are
  computed (text on field and surface, badge text on its own 16% tint over the
  surface and the field, the persona accent gate) for every persona and scheme;
  the manifest's `personas` block survives `load_bundled`; and the stale-age
  threshold exports as a duration.
- `packages/hive-conductor/backend/tests/test_design_service_startup.py` (+1) —
  no test was written; `TestTheDefaultSystemIsReal` is parametrized over
  `BUNDLED_SLUGS`, so the seventh slug collects one more case.
- `packages/hive-conductor/backend/tests/test_design_systems_route.py` (+1) —
  `GET /v1/design/systems` carries each system's `personas` contract, present
  for `workspace` and `None` for the vendored brand systems.

Nothing was removed or renamed.
