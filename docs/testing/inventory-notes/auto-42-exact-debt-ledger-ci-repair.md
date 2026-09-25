---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---
# auto-42 exact-debt-ledger CI repair (L42 repair, head 0c7eabf52)

CI-repair round for the vulture per-identity ledger, per the lane brief. No
tests were added or removed; the only tree change is one banked identity in
`quality/vulture-baseline.json`, produced by the script's own `--update` mode.

## What failed and why

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` at HEAD listed exactly one
unbanked identity: `packages/maistro-server/src/maistro_server/api/a2a.py:62
create_a2a_task` under `fastapi-route-handler`. It is a live A2A admission
route (`POST /tasks/create`, decorator-dispatched, covered by
`test_a2a_api.py` including the replay-dedupe evidence test), so it is a
reviewed retained identity, not dead code. Earlier branch-caused findings
(`_create_child_run`, `find_child_run_by_effect`) were already resolved in
prior rounds; this is the last one.

## The amendment

`--update` with the CI scan args rewrote the candidate ledger's
`fastapi-route-handler` findings from the current classification: exactly one
inserted line (`...api/a2a.py::unused function 'create_a2a_task'`, 41 → 42
banked identities). The candidate "Authorized debt must also be banked in the
candidate ledger" axis is now clean; re-running enforcement shows no
candidate-ledger deltas and no pruning debt.

## Residual (trusted-base axis, orchestrator-side)

Enforcement still exits 1 on `unauthorized` for this one identity because
`load_authorizations` reads `quality/ratchet-authorizations.json` from the
merge-base revision (ba2f1f077) — a branch-side grant cannot authorize its own
debt by design. Closing it needs the documented two-merge flow: a reviewed
grant lands on develop, then this branch syncs develop and the gate passes
with the candidate ledger already banked. Editing the grant file from this
lane is out of scope for the brief (which authorizes `vulture-baseline.json`
only) and structurally inert.

## Re-validation battery at this round's final head

- `ruff check .` exit 0; `ruff format --check .` 2496 files clean.
- Gates: check-execution-lifecycles, check-lifecycle-provenance,
  check-ratchet-provenance, check-shipped-surface-truth,
  check-suite-inventory, check-reachability — all exit 0.
- pytest: core durable_runs + nodes + a2a + capabilities + runs + runtime
  1996 passed / 217 skipped; server suite 363 passed; explicit evidence runs:
  ambiguous-effect replay guard + attempt executor + chat Attempt recovery +
  A2A API 25 passed, node retry attempts 11 passed, runtime
  cancel/deadline selection 10 passed.
- Issue statuses verified read-only: #1169 CLOSED, #1170 CLOSED, #1194 OPEN
  (closure action is orchestrator-side; the replay-effect contract itself is
  shipped and regression-locked per issue-1194-replay-contract.md).
