---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/maistro-evolve/tests: +0
  packages/maistro-rsi/tests: +0
---

# auto-42 round 20: full-gate + live-PG re-validation of the develop-merged review head

Independent verification round at `b5b3da5f0754b69d52bd41f0dcc14a78581425a6` —
the round-19 head `fde98c447` plus one merge commit bringing `origin/develop`
`cf4a562b6` (#1829 governed-model tool-choice fix, M4-C evolve/rsi) into the
lane. No lane-authored code changed in the merge: `git diff fde98c447..b5b3da5f`
touches 15 files, none under `maistro/runs`, `maistro/graph`, or the Attempt
executor/invocation surface (verified byte-identical).

## Quality gates re-run first-hand at this head (all exit 0)

- `check-radon-baseline.py` — the round-19-era C(12)→C(11) `invocation.py:666`
  improvement is banked in the candidate ledger (exit path fails only on
  *candidate*-ledger improvements; the single remaining "improved" line is vs
  the trusted merge-base ledger and is bookkeeping by design).
- vulture (CI args: `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`),
  reachability, reachability-dispositions surface via lifecycles
  (`check-execution-lifecycles.py`, 19/19 classified), promotion surface,
  owned-store access, agent-store writes, backlog consistency, and
  `check-suite-inventory.py` across all **14 suites** — including the
  merge-touched `maistro-evolve` (926) and `maistro-rsi` (858).

## Live PostgreSQL executed first-hand at this head (round-19 closure carried forward)

Lane-private container `auto42-verify-pg` (`pgvector/pgvector:pg18`,
127.0.0.1:54334, `maistro`/`maistro`/`maistro_test` — CI's exact service env
from the `postgres (pg18)` job). CI step sequence, in order:

- `pytest tests/migrations/` — **98 passed**; `alembic upgrade head` → `051`,
  `downgrade base` → `upgrade head` round trip clean.
- `pytest packages/maistro-core/tests/persistence` — **705 passed**;
  `test_container_postgres.py` — **15 passed**.
- `MAISTRO_REQUIRE_PG_LEGS=1` workspaces — **328 passed, 2 skipped** (both
  skips are the documented single-writer backend interleavings, not PG legs);
  canvas supported path — **7 passed**.

## Lane battery over live PG at this head

Driver leg (17 paths) plus the #1170/#1194 proof suites, all with
`MAISTRO_REQUIRE_PG_LEGS=1` and the `MAISTRO_TEST_PG_DSN` env —
**714 passed, 0 skipped, 0 failed**, including `graph/durable_runs/
test_attempt_executor.py`, `test_ambiguous_effect_replay_guard.py`,
`runs/test_spine_conformance.py`, `runs/test_chat_attempt_recovery.py`,
`runs/test_crash_window_invariants.py`, `capabilities/test_pg_invocation_store.py`,
and `formal/models/test_run_lease_fence.py` (the 124 PG skips of the driver's
no-PG run all executed here).

Merge-touched tests re-run: `test_governed_model_tool_choice.py` plus the five
evolve/rsi suites — **100 passed**.

## GitHub state observed (read-only)

PR #1326 head = `b5b3da5f`, draft, body contains only `Refs #42`; branch-only
commits carry no `Fixes/Closes/Resolves` keywords. #1169, #1170 and #1194 are
CLOSED; #42 remains OPEN. No GitHub mutations performed this round.
