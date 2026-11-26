# L337 repair round 4 — handoff (2026-10-24)

Head entering this round: 5eeb94661adfc (develop base for the round:
f956a8142). Head leaving: the round-4 commits on auto-337.

## Previous block resolved: "worker left uncommitted work"

The round-3 worker's result (`2dd0f453`) recorded end status `?? .cache/`
only — an untracked trivy scan cache, not source work. Everything else was
already committed (`aef3245a0` fixes + `5eeb94661` handoff); the tree was
clean at the exact expected head. Nothing to salvage; the `.cache/` dir
stays untracked (scanner artifacts, not tree content).

## New evidence this round acted on: develop moved under the branch

`origin/develop` advanced to `f956a8142` (2 commits past the old merge base
`4de7e906d9`):

- `461fb86b1` — the same supply-chain bumps this branch shipped
  (fastmcp 4.1.3, setuptools 84.2.1, pypdf), **plus** an independent fix of
  the same `check-image-lock-reconciliation.py` forked-pin bug this branch
  fixed in round 3 (the 1182 lane, merge-queue run 40085096483);
- `f956a8142` — M2-A10 concurrent DAG-Run bounding (concurrency, stores,
  health endpoint) with its own tests and `quality/ac-state-notes/auto-1182.json`.

Without a sync, the next merge-queue evaluation would have hit real
conflicts in the reconciliation gate (both sides rewrote `parse_expected`)
and lock files.

## Sync merge `64256fabc` — resolved in place

- `scripts/check-image-lock-reconciliation.py`: develop's implementation
  wins (canonical, functional superset: per-name version sets for
  unconditional AND conditional pins, `_expected_clause` mismatch
  rendering). This branch's round-3 version had no unique semantics.
- `tests/test_check_image_lock_reconciliation.py`: union — develop's 5
  split-resolution tests + this branch's 3 forked-pin tests, with the
  undeclared-version message assertion re-pointed at the `one of ...`
  clause form. 35 gate tests green.
- `uv.lock`, both frontend package-locks: auto-merged; `uv lock --check`
  passes; pypdf 6.21.2 / beartype 0.22.9+0.23.1 fork / fastmcp 4.1.3 all
  present; the merged canvas lock is byte-identical to both parents.
- Inventory deltas: unchanged on this branch's notes; develop's `tests/: +5`
  rides on its own `1182-image-lock-split-resolution.md` note. The
  reconciliation is documented in `auto-337-a36c.md`.

## Gates re-run green at final head 64256fabc

- ruff check + format clean; vulture ledger 1302==1302 with CI's exact
  args (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`),
  base now reading f956a8142.
- OpenAPI types-drift gate: `dump-hive-openapi.py` + `git diff --exit-code`
  on `types.gen.ts` → clean (round 3's committed blob still byte-matches).
- Durability suites (the issue's evidence): 113 passed across
  test_durable_node_metrics / test_feedback_route / test_goal_inspection /
  test_node_metrics.
- Full root suite (CI `test` job's step, CI env): 5646 passed / 143
  skipped — the "Event loop is closed" annotations remain passing-suite
  teardown warnings from develop's aiosqlite lifecycle, not failures.
- packages/maistro-core/tests/runs 1449 passed / 347 skipped;
  packages/maistro-server/tests 646 passed / 8 skipped (develop's
  concurrency + health changes ride through the merge cleanly).
- Full hive suite: 3966 passed / 25 skipped.
- check-suite-inventory: all 21 suites match, 34171 unique identities,
  0 duplicate evidence.
- check-ac-state `--run-tests --ratchet` → OK (45 notes folded at
  f956a8142, incl. develop's auto-1182.json); `--mandate f956a8142` →
  "every criterion this change declares is proven", chain mandate clean.
  The gitignored `quality/ac-state.json` it writes was removed afterwards
  (filesystem-scanning classification test).

## Issue #337 acceptance state (unchanged by this round, re-verified)

- Durable owners wired in production: `foundation._init_state` configures
  the registered node-metrics store; `dag_run_inspection._fresh_store()`
  reloads the shared projection before every HTTP read; feedback requires
  canonical Run/NodeRun/Attempt identity (projection-only runs are 409).
- `set_outcome_store` has a production caller (pinned by
  `test_thumbs_read_through_the_protocol.py`).
- Retention is explicit at `GET /v1/dag-metrics/retention` (no ad-hoc
  deletion; canonical Run retention owns execution records).
- Restart/multi-instance parity: writer, running replica, and post-restart
  store read the same observation (test_durable_node_metrics.py).

## Residual risks

- Hosted CI at 64256fabc not yet observed; all fixes proven against CI's
  exact commands locally. If develop moves again, the same sync discipline
  applies.
- The aiosqlite `Event loop is closed` teardown warning in
  `packages/maistro-server/tests/api/test_user_model_api.py` remains a
  warning inside a passing suite (outside this issue's scope).
