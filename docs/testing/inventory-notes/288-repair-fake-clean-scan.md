---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
---

# #288 repair round — remove the fake-clean scan response

Repair of the prior NEEDS-REPAIR verdict (3 findings). No new collected node
IDs: the contract test and the provenance assertions were strengthened in
place, so `packages/hive-conductor/backend/tests` stays at its recorded total
(3804). The original `+12` lives in `288-scan-surface-contract.md`.

## Finding 1 — the coverage census was hollow (fixed)

`test_scan_contract.py::test_the_real_scan_routes_are_behaviorally_covered`
asserted `set(coverage) == set(EXPECTED_SCAN_ROUTES)` but never read the
`coverage` *values*, so deleting `TestTheScanActuallyScans` (the malicious /
clean / broken-scanner cases) still passed while the docstring claimed
behavioral coverage existed.

Fix: the registry entries now name the specific class/function that walks each
surface's fixtures, and a new `_assert_behavioral_scan_coverage` helper parses
each referenced file's AST and asserts the symbol exists (a class must carry at
least one `test_*` method). Proven non-hollow: a deleted/renamed symbol or a
missing file now raises `AssertionError` (verified out-of-band against
`TestTheScanActuallyScansDELETED`, a missing path, and a non-test symbol).

## Finding 2 — doc claimed a stamp the code did not store (fixed)

`SECURITY.md` claimed stored agent definitions carry scanner / target /
scanned_at / scanned_values in `config["provenance"]["scan"]`, but
`_provenance` stored only scanner / boundary / status / findings / scanned_at,
and Forge's `config["forge"]["scan"]` stored only boundary / status / findings
/ scanned_at.

Fix (makes the documented intent real, not a doc weakening): both blocks now
carry the scan's own full self-describing stamp.
`services/agent_materialization.py::_provenance` now records `target` and
`scanned_values`, keeps `scanned_at` from the scan itself, and takes `boundary`
from the scanner. `routes/agents.py::forge_agent` passes a meaningful
`target={"kind": "agent_definition", "id": aid}` to the scan and records the
same stamp in `config["forge"]["scan"]`. `SECURITY.md`'s claim is tightened to
name the scanned write paths (CRUD, Forge, chat-tool) and to note that
persona-spawn / canonical-roster materialization are *not* scanned write paths
(they carry no fabricated stamp). New assertions guard both stored blocks
against regression (they KeyError against the pre-fix code).

## Finding 3 — reachability ratchet (pre-existing, owner-held, NOT fixed here)

`scripts/check-reachability.py` reports `maistro.runs.admission_identity` as
newly unreachable. Verified pre-existing and out of #288's scope: the module
exists at the develop base `e20e9f52e`, the branch diff
(`e20e9f52e..d921a460`) touches no `maistro-core`, and it is absent from
`quality/reachability-baseline.json`. The reachability ledger may only be
amended by its owner; #288 neither caused nor may resolve it.

## Also surfaced this round — vulture per-identity ledger (pre-existing, owner-held)

`scripts/check-vulture-baseline.py` fails on develop-side desync unrelated to
#288: two unbanked identities (`dags/__init__.py::get_dags_by_department`,
`dags/author_selector.py::get_writing_context`, both 60%) and one stale row
(`maistro-bootstrap/.../session.py::get_session_defaults`). Proven pre-existing
by scanning a read-only `git archive d921a460` of the parent tree: the same two
identities are already flagged and `get_session_defaults` is already unflagged
there. The branch diff touches none of those files or the ledger, and this
round's edits introduce zero new vulture identities. A floor raise needs a
grant landed from the merge base (two-merge rule); that is owner-held and out
of #288's scope.

## Validation

- `uv run pytest packages/hive-conductor/backend/tests -q` → **3780 passed, 24
  skipped** (full backend suite).
- `uv run ruff check` / `ruff format --check` on all changed files → clean.
- `scripts/check-suite-inventory.py` → ok, `packages/hive-conductor/backend/tests: 3804`.
- `scripts/check-agent-store-writes.py` → ok (no new `stores.agents` mutation).
- `scripts/check-security-inventory.py` → ok.
- `scripts/check-doc-links.py` → 0 broken links.
- `scripts/check-vulture-baseline.py` and `scripts/check-reachability.py` → red
  on the pre-existing develop-side desync documented above (not attributable to
  #288; owner-held).
