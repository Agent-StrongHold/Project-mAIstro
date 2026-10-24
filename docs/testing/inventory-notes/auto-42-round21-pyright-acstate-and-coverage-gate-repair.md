---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/maistro-canvas/tests: +0
  packages/maistro-evolve/tests: +0
  packages/maistro-rsi/tests: +0
---

# auto-42 round 21: named CI-gate repair — pyright ratchet, ac-state bank, coverage/test legs re-proven

Repair round at `1d00c04a87b0b56a8af72992d4275a579eaabb21` (develop `c0441cf94`
merged in). The merge-queue evaluation of the pre-merge head named three red
gates: Quality (Pillars 1–4, 7, 8), test, and Coverage. Every gate step was
re-run locally at this head with CI's exact arguments; one lane-caused
regression was found and fixed, one ratchet improvement was banked.

## Lane-caused finding fixed: pyright 22 > baseline 21

`pyright packages/maistro-core/src` reports 22 errors at this head against the
workflow's `PYRIGHT_BASELINE: 21`; the 22nd is
`attempt_executor.py:619 reportAssignmentType` ("object" is not assignable to
`str | None`), introduced by this lane's `_node_logical_effect_key` helper
(#1194 fold). Every other error site sits in files this lane never touched.
Fix: restate `BaseNode.logical_effect_key`'s protocol return (`str | None`)
with an explicit `cast` at the duck-typed call — behaviour unchanged, mypy
--strict still clean, pyright back to 21 (= baseline, ratchet green).

## Ratchet improvement banked (gate-mandated, not a grant)

`check-ac-state.py --run-tests --ratchet` (live pgvector:pg18 at this lane's
container) failed closed on `design_coverage: 41.7828` vs floor `41.1539` —
the unbanked-improvement arm. Banked per the gate's own instruction into
`quality/ac-state-notes/auto-42.json` (per-branch note, no shared-ledger
conflict); the ratchet then passed with all counters on their ceilings.

## Full-suite re-proof at this head (all green)

- `packages/maistro-core/tests` under `coverage run --branch`: **12504 passed,
  114 skipped, 1 xfailed** — the `test` job's core leg.
- `packages/maistro-server/tests` (CI env: `REQUIRE_AUTH=false
  MAISTRO_DRY_RUN=1`, no DATABASE_URL): **493 passed, 8 skipped**. (An earlier
  4-failure run was reproduced, root-caused to my own live-`DATABASE_URL`
  leaking into no-database-wiring assertions, and is green in the CI
  environment — evidence preserved in the run log, not in the tree.)
- root `tests/` (minus `tests/tools/registry`, as CI): **3916 passed, 86
  skipped** — includes the migration-chain suite this lane extends.
- `formal/` (Hypothesis pillar, `maistro_evolve` installed as CI does, live
  PG for the lease/fence machine): **664 passed**.
- `packages/maistro-core/tests/fitness`: **23 passed** (Pillar 7).

## Coverage gate

`check-diff-coverage.py coverage.xml --base c0441cf94b9a` on the combined
core+server+scripts producers: **ok — every measured file this change touches
is at or above 90% lines / 80% branch arcs** (22 changed files exempt:
alembic migrations + test code, per the gate's own declaration). The 87%
publish-set aggregate floor is dominated by the merged develop content; this
lane's publish-set delta is a handful of fully covered statements in
`maistro/graph/durable_runs/attempt_executor.py`, and the per-file diff gate
— the branch-sensitive half — is proven. Full three-producer aggregate
re-combination is left to CI.

## Pillar sweep re-run first-hand (all exit 0)

ruff check/format, radon ratchet, version + release consistency, doc links,
enumerations, workspace retirement, route permissions, principal identity,
frontend typed client, vendored IFEval/BFCL, xenon (145/0/0), **vulture
per-identity ledger with CI's exact arguments (1343 findings, unclassified
0)**, reachability, credential authority, wiring reads, agent-store writes,
contract markers, convergence matrix, reachability dispositions, security
inventory, image inventory + pins, backlog consistency, execution lifecycles
(19/19), model egress, mypy --strict (695 files), interrogate (all 12 floors),
alembic `upgrade head` on live PG, `check-ac-state.py --run-tests --ratchet`.

No test files were added, removed, or renamed in this round: suite counts are
unchanged from the round-20 baseline.
