---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 develop sync round 3 (merge resolution at 0e8755a75)

The repair round started with the worktree left mid-merge: an in-progress
`git merge` of origin/develop (dc9a6b1db, task-stream ownership probe #1180
and its dependency train) into auto-42 at 085fca605, with exactly one unmerged
path: `packages/maistro-core/src/maistro/runs/__init__.py`. Both sides had
added exports — the branch side `RunEffectClaim` (from the #1194
effect-scope claim work in `maistro.runs.store`) and the develop side
`RunConcurrencyExceeded` / `RunConcurrencyLimits` (from the new
`maistro.runs.concurrency` module). The import block had merged cleanly with
both imports present; only the `__all__` list conflicted.

## Resolution

`__all__` now contains all three names (`RunConcurrencyExceeded`,
`RunConcurrencyLimits`, `RunEffectClaim`), matching the merged import block.
Sanity-checked by import at the merged head:

```
uv run python -c "from maistro.runs import RunEffectClaim, \
RunConcurrencyLimits, RunConcurrencyExceeded, RunExecutionService"
-> merged exports OK
```

Merge committed as 0e8755a753e5. No product code beyond the `__all__`
union; no tests added or removed, hence `inventory-delta: +0`.

## Focused validation re-run at merged head 0e8755a75 (all green)

- `uv run ruff check .` -> "All checks passed!"; `uv run ruff format
  --check .` -> "2602 files already formatted".
- `uv run pytest packages/maistro-core/tests/capabilities
  packages/maistro-core/tests/runtime -q` -> **368 passed** (includes the
  #1194 replay/effect-contract suite and the #1169 cancellation/deadline
  runtime suite).
- `uv run pytest packages/maistro-core/tests/runs -q` -> **964 passed,
  226 skipped** (includes develop-side `test_run_concurrency_limits.py` and
  branch-side durable-runs recovery tests — both bodies coexist green).
- `test_ambiguous_effect_replay_guard.py` +
  `test_chat_attempt_recovery.py` -> **14 passed** (one physical dispatch
  under ambiguous provider failure; chat lease/reclaim/terminal-write
  recovery).
- `uv run pytest packages/maistro-server/tests/api/test_a2a_api.py -q`
  -> **1 passed**.
- `scripts/check-suite-inventory.py` -> ok, **14/14 suites match** the
  recorded inventory (develop's new test files are counted by develop's own
  inventory updates that merged cleanly).
- `scripts/check-merge-markers.py` -> ok, no conflict markers in any
  tracked file.
- `scripts/check-execution-lifecycles.py packages/*/src` -> **19/19
  classified lifecycles, 0 violations** (3 CANONICAL, 8 CONVERGE, 6 DOMAIN,
  2 PROJECTION) — no physical-execution bypass.
- `scripts/check-lifecycle-provenance.py` -> **0 lifecycle violations**.
- Exact CI vulture invocation, `RATCHET_BASE_REV=origin/develop`:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` -> **exit 0, 1403 reviewed identities = 1403 findings,
  unclassified 0** (count moved 1404 -> 1403 from develop's own merged
  changes; the shared ledger merged cleanly and needed no amendment).

## Acceptance state at this head

Effect-scope-keyed durable uniqueness is present in all three schema
surfaces (`capabilities/invocation_store.py`, `capabilities/pg_invocation_store.py`,
`alembic/versions/035_capability_invocations.py`: unique
`(run_id, effect_scope, binding_id, effect_key)` with legacy backfill).
GitHub read-only: #1169 CLOSED, #1170 CLOSED, #42 OPEN, **#1194 still
OPEN**. The sole residual remains the upstream #1194 closure (orchestrator-
side, via delivery PR #1319 or supersession); everything in-tree for #42 is
proven green at 0e8755a75.
