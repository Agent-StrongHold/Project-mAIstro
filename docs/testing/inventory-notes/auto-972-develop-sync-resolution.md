---
inventory-delta:
  tests/: +0
---
# auto-972-develop-sync-resolution

Repair round for #972 ([M9-G4] Quarantine or disable misbehaving extensions
from canonical security and health evidence): resolved the preserved
develop-sync conflict (two-step merge) and re-validated the implementation on
the merged head; no tests added or removed.

## Merges resolved

1. **e20e9f52e** (029d1ad17): the in-progress merge found preserved in the
   worktree. One conflict —
   `packages/maistro-core/src/maistro/extensions/__init__.py` docstring:
   develop's side simply predates this branch's M9-G4 layer, so the
   resolution keeps the branch's `#972 quarantine/health response` bullet on
   top of develop's text. Diff vs develop's file is exactly the quarantine
   additions (bullet + `maistro.extensions.quarantine` import + `__all__`).
2. **origin/develop 252950bdb** (cb1f95f5d): the current develop head. Three
   conflicts, all additive-on-both-sides:
   - `_vulture_whitelist.py`: kept both the #972 quarantine whitelist block
     and develop's #971 `ScopeBoundExtensionState`/`TenantScopedExtensionState`
     block; the import section had auto-merged both sides cleanly.
   - `maistro/container.py`: kept both the quarantine fields/TYPE_CHECKING
     imports (#972) and develop's policy-engine/runtime-state fields (#971).
   - `maistro/extensions/__init__.py` `__all__`: kept both
     `"ViolationSeverity"` and `"WorkspaceExtensionEnablementPolicy"` in sort
     order.

## Ledger reconciliation (quality/vulture-baseline.json)

Per the quality-gates rule, the auto-merged ledger was diffed against both
parents before trusting it: git's hunk merge had produced 1322 rows while each
parent carried 1324. A conservative multiset-union (1326) was tried first and
**rejected by the gate itself**:
`check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` reported exactly 4 recorded identities no longer
produced by the merged tree (feedback.py `LOW`, fixer_genome.py `LOW`, and the
2 duplicated `personas/store.py::get_for_workspace` rows). The ledger was
pruned of exactly those 4 gate-named rows; the gate now passes with
`1324 reviewed identities -> 1322 findings`, 0 unclassified. No debt was
added; no grant consumed or required.

## Validation on merged head cb1f95f5d (all green)

- `uv run ruff check .` / `uv run ruff format --check .`
- `uv run pytest packages/maistro-core/tests -q` → 15622 passed, 1154
  skipped, 7 xfailed (includes the 43 #972 quarantine-authority tests);
  `tests/a2a` → 282 passed
- `uv run pytest tests/test_check_compliance.py
  tests/security/test_sentinel_permission_table_armed.py
  tests/cross_product_parity -q` → 134 passed
- canonical mypy over all seven package src trees → no issues in 916 files
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
- `uv run python scripts/check-ratchet-provenance.py` → exit 0
- `uv run python scripts/check-suite-inventory.py` → 21/21 suites match the
  recorded inventory (required `uv sync --locked --all-extras` first: the
  merged uv.lock adds the reference-gallery packs as workspace members, and a
  stale venv surfaces as a collection error, not inventory drift)
