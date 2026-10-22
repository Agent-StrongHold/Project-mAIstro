---
inventory-delta:
  packages/maistro-core/tests: +0
---

# Issue 41 CI repair (round 10): develop-sync conflict resolution and re-validation

Round scope: resolve the develop-sync conflict block preserved in the worktree
(an in-progress merge of `origin/develop`@`b0fcfcc8a` with one unresolved path),
merge the current `origin/develop` (`80ce0d998`), and re-run the validation
battery. No test cases added or removed; the node-ID count of
`test_idempotency_purge_driven.py` is unchanged, so the collected-case count is
unchanged.

## Conflict resolution (cfdcdc085)

`packages/maistro-core/src/maistro/tasks/idempotency.py` combined both sides:

- branch (#1176): the `Ambiguous` claim outcome — `| Ambiguous` kept on the
  wrapper `claim`, on `_claim`, and on the `Protocol.claim` annotation;
  `import uuid` kept for fencing tokens;
- develop (#325): the purge-driven admission — `claim` wrapper,
  `_purge_due`/`_maybe_purge`, `_claim` rename, and `import time`.

`queue.py`'s `Ambiguous` discovery handling needed no change.

## Test adaptation (develop's new suite vs #1176 fencing)

Develop's `test_idempotency_purge_driven.py` predates claimant fencing: three
`complete(...)` calls lacked the now-required keyword `token` (TypeError on
`[memory]`, and by construction on every tier). Each call site now captures the
`Claimed` outcome and passes its token; a fenced write without the token
refuses by design (#1176). 348 passed, 8 skipped
(`uv run pytest packages/maistro-core/tests/tasks -q`).

## Ac-state re-bank

`quality/ac-state-notes/auto-41.json` re-banked at design_coverage 33.607
(`--run-tests --ratchet --bank` on a fresh pgvector pg18, `RATCHET_BASE_REV=origin/develop`).
The prior value (38.0924) predates the develop sync. The ratchet's
recorded-floor comparison (33.9095) still fails locally, and reproduces
bit-for-bit on the pristine `80ce0d998` base measured in the same detached
worktree and environment (also 33.607 over 156 taken decisions): the fall is a
pre-existing property of the base's recorded floors versus this environment,
not a candidate regression. The per-change mandate passes ("every criterion
this change declares is proven"; "adds no spec, decision or criterion-less
document"). CI — which measures with its full service set, where a skip counts
as not-passing — is the authoritative environment for the recorded floors.

## Re-validation battery (all from the merged head 36b65d36)

- `uv run ruff check .` / `ruff format --check .`: clean (2561 files).
- `uv run mypy packages/maistro-core/src`: clean (633 files).
- tasks suite 348+8sk; runs admission + chat admission + server tasks
  idempotency 56 passed; chat gate + backlog-consistency tests + conductor HA
  confirm 81 passed; conductor engine service 35 passed.
- `check-vulture-baseline.py` (per-identity, `--min-confidence 60`): exit 0,
  1412 = 1412, no new unbanked identities.
- `check-radon-baseline.py` (canonical no-arg scope = `packages/maistro-core/src`):
  exit 0, 68 -> 68. (A broader `packages/*/src` scan flags
  `maistro_registry/linker.py:_fetch_ids` C(11), which CI's invocation never
  scans and no baseline ever covered — out of gate scope.)
- `check-backlog-consistency.py`: ok (151 items).
- `check-durable-table-inventory.py`: ok (63 tables) from a non-root CWD; the
  gitignored root `.env` (`API_KEYS=test` vs `list[str]` JSON parsing) breaks
  Settings-importing runs from repo-root CWD — environment, not tree (CI has
  no root `.env`); the same hazard is documented in round 9.
