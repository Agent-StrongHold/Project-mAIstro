---
inventory-delta:
  packages/maistro-core/tests: +15
---

# Issue 41 CI repair (round 12): cover the diff-coverage failures, sync develop

Round scope: repair the two red CI gates at head `ca3f1b7d`
(run 36224539094). Evidence was fetched from the failed jobs themselves
(`gh api .../jobs/108355883228/logs`, `.../108356811906/logs`), not guessed.

## What failed, and the fix

1. **Quality gate, step "acceptance-state ratchet + mandate"**: "authorized
   floor(s) independent landings have superseded — design_coverage: 3 notes
   (auto-1138.json, auto-1158.json, auto-48.json) already clear it on their
   own; prune it from quality/ratchet-authorizations.json." `origin/develop`
   (`9e9f5037e`) already pruned `ac-state.design_coverage@33.9095`; merging
   develop into `auto-41` (clean merge) brings that fix. Verified locally:
   `check-ac-state.py --run-tests --ratchet` exit 0 ("OK: 10 debt counters
   sit exactly on their ceilings...").
2. **Coverage gate, step "Diff coverage gate (per file, lines 90% / branches
   80%)"**: 5 maistro-core files under the floor:
   `runs/pg_store.py` (33.3%, uncovered 562, 570),
   `runs/sqlite_store.py` (20%, uncovered 450, 458–460),
   `runs/store.py` (75% of 4 branch arcs, partial at 1092),
   `tasks/admission.py` (76.9%, uncovered 164, 452, 453),
   `tasks/queue.py` (86.5%, uncovered 260, 265, 441–444, 481, 511, 514,
   557, 558, 560, 586, 649).

   All are #1176/#41 admission-idempotency edges landed by earlier rounds of
   this branch without their seam tests. Fixed by real tests, not by pruning:

   - `tests/runs/test_spine_conformance.py` +
     `test_a_task_receipt_finds_its_run_and_only_that_run` — the
     `find_run_by_task_receipt` discovery lookup conformed across the
     memory/sqlite/postgres spine (found, only-that-run, and None). Covers
     pg_store 562/570 (both branches of the JSONB path lookup), sqlite_store
     450/458–460, and store.py 1092's loop arcs (match and no-match).
   - `tests/tasks/test_idempotency.py` + 12 cases:
     `test_a_malformed_admission_scope_is_refused_before_any_claim`
     (queue.py:260), `test_a_router_without_the_scope_seam_still_scopes_and_
     reconciles` (queue.py:265 routing fallback),
     `test_a_bound_admitter_scopes_only_its_own_workspace` (admission.py:164
     WorkspaceNotAdmissible), `test_the_routing_admitter_resolves_receipts_
     workspace_independently` (admission.py:452–453 + routing discovery),
     `test_a_claim_superseded_before_begin_replays_the_winner` /
     `..._when_the_row_is_gone` / `..._when_the_winner_dies` (queue.py:441–444,
     557–558, 560), `test_a_complete_failure_still_returns_the_admitted_task`
     (queue.py:481), `test_a_fence_refusal_cancels_the_orphan_and_fails_
     retryably` (queue.py:586 + compensation), `test_an_ambiguous_claim_
     without_a_spine_mints_fresh` (queue.py:511), `test_an_ambiguity_
     undecidable_by_the_admitter_fails_visibly` (queue.py:514),
     `test_a_replay_without_a_spine_returns_the_receipt_unqueued`
     (queue.py:649).

   The postgres leg needs `MAISTRO_TEST_PG_DSN`; in CI the coverage-postgres
   producer runs `packages/maistro-core/tests/runs` with the DSN set, so the
   new spine case is measured there exactly like the rest of the suite.

## Local reproduction of the gates

- `coverage run --branch --source=packages/maistro-core/src/maistro -m pytest
  packages/maistro-core/tests` with `MAISTRO_TEST_PG_DSN` pointed at a local
  pg18 container: 11109 passed, 1 xfailed, 1 failed —
  `test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_
  fallback` fails only under this environment's `--timeout=60` because WSL
  takes ~61s to time out a connect to port 1 (CI runners refuse instantly);
  it passes standalone in 61.7s. Environment timing, not a code failure; it
  touches none of the gate's changed files.
- Appended the maistro-server and hive-conductor producers
  (394 passed / 2820 passed, 6 skipped), regenerated coverage.xml, and ran
  `scripts/check-diff-coverage.py coverage.xml --base origin/develop`:
  **ok: every measured file this change touches is at or above 90% lines /
  80% branch arcs** (exit 0).

## Vulture per-identity duty (exact-debt-ledger round)

`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'`: exit 0, 1412 reviewed identities → 1412
findings, unclassified 0. The round changes no src identities, so
`quality/vulture-baseline.json` is unchanged — nothing to bank, nothing
eliminated.

## Full battery at this head

`ruff check .` clean; `ruff format --check .` 2574 files formatted;
`mypy` over the six package src trees clean (721 files);
`pytest packages/maistro-core/tests/{tasks,runs}` 1457 passed, 3 skipped;
`pytest tests/migrations` 100 passed (pg); maistro-server 394 passed;
hive-conductor 2820 passed, 6 skipped; `check-ac-state.py` exit 0;
`check-radon-baseline.py` 67 → 67; `check-suite-inventory.py` ok;
`check-merge-markers.py` ok; `check-durable-table-inventory.py` 63 tables ok;
`check-backlog-consistency.py` 151 items ok; `check-m1-convergence-freeze.py
--base origin/develop` no unapproved island.
