# L80 ac-state ratchet — round 5: the "inherited floor" was a service-less measurement

Round 4 (commit `602cc2a8d`) concluded the residual `design_coverage
33.0728 < 38.0924` failure was inherited from the mandate base and not
repairable in-branch, based on a detached-worktree base measurement that read
the identical 33.0728. Round 5 re-ran those measurements **with the
PostgreSQL service the AC-marked suite gates on** (`MAISTRO_TEST_PG_DSN`) and
that conclusion was wrong: the shortfall was environmental, not corpus debt,
and the gate passes on this branch exactly as CI runs it.

## Measurements (all executed this round, head `b37bc32d7`, base `ca4caec7d`)

| Tree | Services | design_coverage | Outcome |
|------|----------|-----------------|---------|
| base `ca4caec7d` (detached worktree) | none | 33.0728 | reproduces the verifier failure |
| base `ca4caec7d` (detached worktree) | PG up | **38.0924** | matches the base's own banked fold — develop is consistent |
| candidate (no DSN) | none | 33.0728 | the verifier's failing run |
| candidate | PG up | **38.0924** | **gate PASSES** (run twice) |

Mechanism: 110 `maistro-core` AC-marked tests (plus 5 conductor and 18 root)
skip on `MAISTRO_TEST_PG_DSN is not set` (e.g.
`packages/maistro-core/tests/runs/test_attempt_result_repair.py:217`). A
skipped AC test leaves its criterion below `passing`, so `design_coverage`
(the fraction of taken-decision criteria at `reachable`) reads ~5 points low.
The 38.0924 floor banked in `auto-1138.json` at `ca4caec7d` was measured with
services, which is why the service-less base measurement "matched" the
service-less candidate measurement and looked like an inherited fall.

## What this round changed

- `quality/ac-state-notes/auto-80.json` re-banked from a service-backed run:
  `design_coverage` 38.0123 with all eleven other counters unchanged. (One
  intermediate full run measured 38.0123 instead of 38.0924: criterion
  `ADR-082526-b36a/AC-7` — the knife-edge lease tests in
  `packages/maistro-core/tests/runs/test_parked_run_resume.py:427`, whose
  0.5 s TTL is documented as "leave room for a real PostgreSQL round trip" —
  flaked once under full-suite load. Stable in isolation, 16/16 twice. The
  note folds by `max`, so a slightly-low branch note cannot lower any floor.)
- The round-4 grant prune (`design_coverage@33.9095` superseded by three
  later notes) and the superseded-grant reporting repair are unchanged and
  remain correct.

## How to run the gate so it measures what CI measures

```
# start PostgreSQL with pgvector (compose service or equivalent), then:
DATABASE_URL=postgresql://... uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql://... uv run python scripts/check-ac-state.py \
  --run-tests --ratchet --mandate <base>
```

Result this round: `OK: 10 debt counters sit exactly on their ceilings and 1
progress counter sits exactly on its floor`; `OK: every criterion this change
declares is proven`; `OK: this change adds no spec, decision or
criterion-less document to the chain.`

Residual risk (pre-existing, out of this lane's scope): the
ADR-082526-b36a lease-timing tests sit close to the PG round-trip latency
budget and can flake under load, which makes the gate's coverage number
run-to-run sensitive by ±one criterion. A dedicated timing fix belongs to the
runs/lease suite, not the sandbox-conformance lane.
