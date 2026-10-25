# #1572 repair round 4 — suite-inventory leg fixed at head 882fd6be6

Round lane: `auto-1572` @ `882fd6be6fff`, develop base `0d49d4e068de`
(merged into the branch in `858c30e88`; `origin/develop` re-fetched this
round and still `0d49d4e068de`).

## What failed and why

The merge-queue evaluation named one failing gate: `integration-scope`. The
driver's deterministic legs (dependency sync, `ruff check`, `ruff format
--check`, scoped pytest) were green; `check-suite-inventory.py` was the one
red:

    DRIFT  packages/maistro-core/tests: expected 16165, collected 16166

The +1 is fully attributable: head commit `882fd6be6` (this branch) added
`test_pack_id_colliding_with_an_active_extension_is_refused` to
`packages/maistro-core/tests/extensions/test_pack_contracts.py` together
with the fail-closed `PackIdentityConflict` guard in
`packages/maistro-core/src/maistro/extensions/packs.py`, and died before
recording the inventory delta — exactly the "validation repair budget
exhausted" hand-off. Nothing stopped collecting: full-tree collection for
this round re-confirmed 17 suites / 30809 node IDs with zero duplicate
evidence, and the drift is the intentional addition, not an alarm.

Because `integration-scope` fails closed when a required specialized leg
fails, the red `suite inventory` step inside CI's `test` job is sufficient
to explain the aggregator failure; no other leg regressed (each re-proven
below or unchanged-in-diff since round 3).

## Repair

Recorded the delta with the gate's own tool and wrote the prose:
`docs/testing/inventory-notes/auto-1572-pack-identity-collision.md`
(front-matter `inventory-delta: packages/maistro-core/tests: +1`). No test,
source, or ledger file was touched by this round.

## First-hand re-validation at 882fd6be6

- `uv run python scripts/check-suite-inventory.py` (CI-exact, all suites):
  **ok — 17 suite(s) match the recorded inventory** (was FAIL).
- CI-exact vulture ledger, because `packs.py` grew six lines after round 3:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **EXIT 0, 1323
  reviewed identities → 1323 findings, unclassified 0, never_allowlist 0**.
  No ledger amendment needed or made.
- Scope resolution pair (CI-exact inputs, 79 changed paths):
  `ci_merge_group_scope.py --json` → EXIT 0;
  `check-integration-scope.py --event-name merge_group --scope-json …
  --required-json` → EXIT 0; required set unchanged: the same nine legs
  round 3 executed green first-hand at `23800125b` (postgres pg17/pg18,
  durable-events, strike-ladder, wheel-imports, hive-conductor-e2e,
  hive-conductor-e2e-ui, object storage, docker-build). The only content
  since that fully-proven head is the develop merge (develop's own,
  CI-validated tip), the two-file pack-identity guard + test, and docs —
  none of which the round-3 legs exercise beyond what the green
  deterministic gates above already cover.
- `uv run python scripts/check-m1-convergence-freeze.py --base 0d49d4e068de`
  → EXIT 0, no unapproved new architecture island.
- `uv run python scripts/check-execution-lifecycles.py` → still the known
  **external** red, sole finding `maistro.goals.model::GoalStatus` with no
  already-landed authorization; `tests/test_check_execution_lifecycles.py`
  → 1 failed / 28 passed, same root cause. `origin/develop` still lacks the
  grant, `load_authorizations` reads it from the merge base, and this lane
  may not edit grants — the two-merge blocker documented in round 3 stands
  unchanged.
- Focused behavior: goals + runs suites **1266 passed / 302 skipped**
  (PostgreSQL legs skip without a DSN, as designed);
  goal wiring + Run binding **16 passed / 5 skipped**; pack contracts
  **110 passed** including the new collision test, asserted from both sides
  (refusal raised, no record created).
- `uv run ruff check .` / `uv run ruff format --check .` → green (3249
  files); `check-durable-table-inventory.py` → ok, 110 tables;
  `uv run alembic heads` → single head `062` (canonical goals).

## Residual risk

The nine integration-scope legs were executed first-hand at `23800125b`
(round 3), not re-executed at this head; the diff between the two heads adds
no path those legs classify beyond what this round's green gates cover. The
GoalStatus grant remains the sole known red anywhere and can only close by
landing on develop first.
