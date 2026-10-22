---
inventory-delta:
  packages/maistro-ext-sdk/tests: +83
---
# Issue 949: extension SDK package and machine-validatable manifest schema

New package `packages/maistro-ext-sdk` (import root `maistro_ext_sdk`): the
M9-A1 public extension SDK — a versioned extension contract
(`contract_version()`, literal in `contract.py`, independent of the lockstep
application version) and a strict Pydantic manifest schema (identity,
publisher, version, contract range, closed extension families, closed
authority vocabulary for capabilities/effects/data/network/filesystem/
secrets, dependencies, optional features, and declarative entrypoint
metadata). Parsing a manifest performs no import of extension code; the
out-of-tree validator (`validate_extension_dir`) stats the entrypoint file
instead of importing it.

## Suite delta is +83

`packages/maistro-ext-sdk/tests` is a new suite (baseline entry 0 in
`inventory/baseline.json`; this note carries its whole count):

- `test_manifest_contract.py` (32) — parse/reject before import, unknown
  authority/malformed declarations fail explicitly, least-authority both
  directions, dependency validation, JSON-schema agreement, single public
  error type, hand-built models through the same pipeline.
- `test_out_of_tree_validation.py` (10) — the shipped example validates from
  a copied directory; import-bomb extensions prove validation never imports
  extension code (in-process and in a fresh interpreter); rejection paths.
- `test_import_hygiene.py` (3) — AST scan: SDK modules import only stdlib,
  pydantic, and themselves; declared deps match the scan.
- `test_contract_version.py` (21) — queryable contract version, structural
  independence from the application version, range semantics.
- `test_yaml_and_io.py` (8) — the optional YAML front door, unreadable/odd
  manifest files, entrypoint-target round trip, default isolation.
- `test_cli.py` (9) — the console validator: exit codes, token-naming
  stderr rejections, no-import proof, schema/version subcommands,
  console-script wiring.

Mutant-checked: disabling the capability→scope cross-field check fails
`test_capability_without_scope_fails`; deriving the contract version from
the application version fails the independence AST test; skipping the
`_validate_least_authority` pipeline stage fails the whole
least-authority class (all against a PYTHONPATH-shadowed copy).

## Gate enrollments in the same change

`check-suite-inventory.py` recipe, `SUITE-INVENTORY.md` row,
`check-dependency-namespaces.py` FIRST_PARTY_OWNERS, `bump_version.py`
pyproject + fallback sites, `verify-monorepo-layout.sh`,
`verify-wheel-imports.py` PACKAGES (release publish set), `check-diff-coverage.py`
MEASURED_ROOTS + matching quality.yml coverage producer, ci.yml test step,
release.yml PUBLISH_SET, root pyproject ruff src / pytest testpaths /
pytest pythonpath.
