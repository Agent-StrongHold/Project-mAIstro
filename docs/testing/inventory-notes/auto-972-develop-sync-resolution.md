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

## Merge 3: `f0fb5c83db86` (the M9-G EPIC WIP) — the direction flips

The merge preserved in this worktree was `f0fb5c83db86` ("WIP: [EPIC M9-G]
Enforce extension isolation, permissions, tenancy, and policy governance
(#2226)"), which is an **ancestor of `origin/develop`** (`5647c34`). Unlike the
earlier syncs, this commit independently landed **issue #972 itself**: develop's
`maistro.extensions.quarantine` ships `ExtensionGovernanceService`,
`GovernanceActor`, `SandboxViolationBridge`, `security_evidence` and
`health_evidence`, plus its own acceptance suite
(`test_extension_quarantine.py`, recorded in `972-extension-quarantine.md`).

Three conflicts, all additive-on-both-sides, and all resolved by adopting
**develop's canonical engine** and superseding the branch's duplicate — the
same pattern as #971:

- `packages/maistro-core/src/maistro/extensions/quarantine.py` (both-added,
  HEAD 1063 lines vs develop 815): took develop's `ExtensionGovernanceService`
  module in full.
- `packages/maistro-core/src/maistro/extensions/__init__.py`: kept develop's
  `maistro.extensions.quarantine` import block and `__all__`; dropped the
  branch's `ExtensionQuarantineAuthority` re-exports and the branch's
  M9-G4 docstring bullet (develop's own bullet covers the module).
- `packages/maistro-core/src/_vulture_whitelist.py`: kept develop's #972
  quarantine whitelist block; dropped the branch's `ExtensionQuarantineAuthority`
  / `InvocationAdmission` / `HealthVerdict` / `InFlightDisposition` rows.

The branch's container wiring (`Container.extension_quarantine_store`,
`extension_quarantine_authority`, `ensure_extension_quarantine_authority`)
and its acceptance suite (`test_quarantine_authority.py`, 43 node IDs) were
removed in the same resolution; they referenced the deleted branch API and
are superseded by develop's engine, which is deliberately not container-wired
(the M9-G host call sites are the follow-up slice). No competing suspension
authority remains: `maistro.extensions.quarantine` is the single writer of
quarantine state.

### Ledger reconciliation (quality/vulture-baseline.json)

The auto-merged ledger was diffed against both parents before trusting it
(AGENTS.md warns that `quality/*.json` merge cleanly while losing rows):
git's hunk merge produced **1319 rows while the merge base
`b664e9a362` carried 1321** — the branch's earlier repair had pruned the two
`…::unused variable 'LOW'` rows on the strength of a *pre-`e02534da3`*
merge, but the merged tree (which now carries the M9-A3 enum members) really
does produce them. `check-vulture-baseline.py` named exactly those two as
unbanked candidate identities, so the ledger was restored to the merge base's
1321-row blob (`05b1261b0`) via the gate's own `--update` writer. The gate now
reports `1321 reviewed identities -> 1321 findings`, exit 0. No debt added;
no grant consumed or required.

### Inventory reconciliation

The branch's deleted 43-test suite left `packages/maistro-core/tests` at
17104 collected vs 17147 expected (−43). `972-extension-quarantine-authority.md`
was rewritten as a superseded note with a **+0** delta (its original +43
zeroed by `check-suite-inventory.py --update --note …`); develop's suite is
accounted for by `972-extension-quarantine.md` (+33). `check-suite-inventory.py`
exits 0 across all 21 suites.
