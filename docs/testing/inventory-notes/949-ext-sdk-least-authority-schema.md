---
inventory-delta:
  packages/maistro-ext-sdk/tests: +9
  tests/: +1
---
# Issue 949 repair: least-authority mode pairing and an honest public schema

Repair review on PR #1982 (Codex, at `d0dc6d1481`) flagged three findings that
were still live at `40df10899b42`; this change closes them.
`packages/maistro-ext-sdk/tests` goes 109 → 118 and the root `tests/` suite
gains the release-notes sync test.

## What moved the count

- `test_manifest_contract.py` (+9):
  - filesystem `mode` ↔ capability pairing, both directions, parametrized
    (+4 invalid / +3 valid): `mode: write` with only `filesystem.read`
    declared, a `filesystem.write` capability under `mode: read`, and the two
    all-both-capabilities mirrors. Before this change
    `manifest_from_json` accepted `capabilities: ["filesystem.read"]` with
    `filesystem: {paths: [...], mode: write}` — the requirement block granted
    what the capability block never declared;
  - the published JSON Schema now encodes the closed authority vocabularies
    and identity patterns (+2): enums/patterns asserted pointer-by-pointer,
    and an out-of-process `jsonschema` check proving a manifest the SDK
    rejects (`host.kernel` capability) fails a pure schema validation too.

- `tests/test_release_guard.py` (+1): the release-notes verification block
  must name every package in `release.yml`'s `PUBLISH_SET`. The notes
  hard-coded five names while the publish set ships six — every generated
  release told consumers the checksums covered fewer packages than it did.

## Production changes under test

- `manifest.py`: `_validate_filesystem_mode_pairing` joins the shared
  pipeline (called from `validate_manifest`, so every parse entry point —
  dict, JSON, YAML, directory — enforces it), keeping each rule a plain
  statically-called function per the module's stated design. Only fires when
  paths are declared: an untouched default block seeks no filesystem
  authority and stays valid. `semantic_json_schema_constraints()` is the
  single source of truth mapping schema pointer → enum/pattern, read
  straight from the closed-vocabulary constants and compiled regexes.
- `validation.py`: `public_json_schema()` splices those fragments in via
  `_apply_semantic_constraints` (deep merge preserves pydantic's sibling
  keys); an unresolvable pointer raises at build time rather than shipping a
  silently unconstrained schema. `family` and `filesystem.mode` were already
  enums (pydantic derives them from their `Literal`s).
- `release_notes.py`: the artifact list names all six `PUBLISH_SET` packages.

## Mutant check

Deleting the `_validate_filesystem_mode_pairing` call from
`validate_manifest` fails the four mismatch cases; deleting the
`_apply_semantic_constraints` call in `public_json_schema()` fails both
schema tests; reverting the release-notes text fails
`test_notes_name_every_package_the_release_publishes`. All three were run
against this tree and reverted; the restored tree passes 142/142
(ext-sdk + release-guard suites).
