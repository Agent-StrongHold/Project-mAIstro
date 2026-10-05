---
inventory-delta:
  packages/maistro-core/tests: +72
---

# #955 (M9-C1) — extension contract versioning, feature negotiation, deprecation policy

Implements the M9-C1 policy layer (ADR-100526-9c55):
`packages/maistro-core/src/maistro/extensions/compat.py` — contract semver
policy independent of the application/package axis, contract-range
compatibility, required vs optional feature negotiation, machine-readable
deprecation status with enforced (future-major, documented) removal targets,
and actionable unsupported-version failure reasons. Host read surface: the
`maistro extensions compat` preflight command (`--json` for the
machine-readable report; exit 1 on incompatible).

**+72 `packages/maistro-core/tests/extensions/`** (collect-only verified on
this head):

- `test_compat.py` (67) — each test names the acceptance criterion it pins:
  metadata-only compatibility proven structurally (negotiation completes with
  `builtins.__import__` banned; the metadata model carries no
  module/entrypoint field); optional features degrade explicitly and are
  absent from `supported_features`; contract-major and same-major misses fail
  with boundary-naming actionable reasons (the contract gate short-circuits
  feature interpretation); deprecations carry machine-readable status,
  required removal targets, and enforced future-major support windows;
  compatibility is independent of application patch version (no such field
  exists; identical decisions across patch-differing hosts) and report text
  never contains module paths; closed machine-readable vocabularies (including the strict
  `parse_feature_status` string→status path) and JSON-safe report projection;
  fail-fast `ensure_compatible`.
- `test_cli_compat.py` (5) — the preflight command: compatible/degraded exit
  0, incompatible exits 1 with reasons, `--json` parses, malformed metadata
  names the offending key, unreadable/invalid JSON exits non-zero.

Fail-before evidence (each mutation reverted before commit): muting the
contract-range gate in `negotiate` fails the major/window tests (2);
rewriting unknown *required*-feature handling to degrade instead of refuse
fails 6 activation-gate tests; dropping the future-major removal-target
validation fails the support-window test (1).

Validation on this head: `pytest packages/maistro-core/tests/extensions` 116
passed (44 pre-existing + 72 new); mypy --strict over the six package srcs
clean (806 files); `ruff check` / `ruff format --check` clean on the touched
trees; `check-adr-index.py`, `check-adr-status-language.py`,
`tools/lint_lifecycle.py`, and `maistro_registry.cli lint . --strict` (433
files) all pass with the new ADR-100526-9c55.
