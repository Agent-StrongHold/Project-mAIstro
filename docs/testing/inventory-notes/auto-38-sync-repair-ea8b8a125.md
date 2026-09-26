---
inventory-delta:
  (no test changes — verification and develop-sync record only)
---

# auto-38 repair round at ea8b8a125: develop-sync resolution + gate re-execution

Two blocks inherited from the previous round were cleared, and the two CI failures
reported at 9f84000bf (Quality gate, Pillars 1–4/7/8; Coverage gate) were re-proven
green at the new head. No product code changed in this round; the only commits are the
develop-sync merges and this note.

## Block 1 resolved: develop sync conflict

The worktree was left mid-merge with MERGE_HEAD at 9e9f5037e (an develop commit that
has since been superseded on the branch) and one unmerged path,
`quality/ratchet-authorizations.json`. Resolution:

1. `git fetch origin`; completed the in-progress merge. The single conflict was
   develop's new `"ac-state": {}` ledger key landing where the branch had also edited;
   the two sides are byte-identical apart from that key (verified by diffing both
   JSON-normalized sides with the key popped), so the resolution is the union: keep
   `"ac-state": {}`. Committed as 23713cfcd.
2. Merged the remaining `origin/develop` (a71fc2e43 #1488, 031bd0746 #1165/#1593) —
   clean, no conflicts. Committed as ea8b8a125. `git merge-base --is-ancestor
   origin/develop HEAD` now holds: the branch fully contains origin/develop.

## The two failed CI gates, re-executed at ea8b8a125

Postgres: lane container `auto-38-repair-pg` (pgvector/pg18, port 5590), fresh DB
`maistro_test` created empty and migrated with `uv run alembic upgrade head` (036→042
chain) exactly as the quality job does. `RATCHET_BASE_REV=origin/develop` for both
ratchet gates, matching a PR candidate against develop.

- **Quality gate** — every step re-run green: ruff check + format, radon ratchet
  (67/67), `bump_version --check` (35 sites), release consistency, doc links (0
  broken), `check_enumerations` (no new gaps), IFEval + BFCL provenance, reachability
  (188 unreachable, all attributed), credential authority, wiring reads, agent-store
  writes, contract markers, convergence matrix, reachability dispositions, security
  inventory, image inventory, backlog consistency, vulture per-identity ledger
  (**1411/1411, unclassified 0, never_allowlist 0 — no unbanked identities, no ledger
  amendment needed**), xenon (67 ≤ baseline 77; note xenon is not in the uv venv and
  had to be `uv pip install`ed first — an earlier "0 violations" reading was the
  binary failing to spawn, caught and corrected), `mypy --strict packages/maistro-core/src`
  (637 files clean), and the acceptance-state ratchet
  (`check-ac-state.py --run-tests --ratchet`, exit 0, 10 debt counters on ceilings /
  1 progress counter on floor, folded from 76 notes at 031bd0746f30; the rewritten
  `quality/ac-state.json` is byte-identical to the committed one — git status clean).
- **Coverage gate** — producers re-run at this head: core
  (`coverage run --branch --source=packages/maistro-core/src/maistro -m pytest
  packages/maistro-core/tests`, PG legs required via `MAISTRO_REQUIRE_PG_LEGS=1` +
  DSNs): **11149 passed** in 375s, 47 skipped, 1 xfailed, 1 failed —
  `test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback`,
  re-run in isolation with `--timeout=120`: **passed** in 61.8s (the WSL port-1 TCP
  connect hang exceeds the suite's 30s per-test cap; CI's network fails fast). The
  file is not in the branch diff. Server producer, run exactly as CI's combine step
  does (no PG env — that job has no database service): **393 passed**. Combined XML
  fed to `check-diff-coverage.py --base origin/develop`: **exit 0** — 7 changed files
  measured, all ≥90% lines / ≥80% branch arcs; the 3 changed test files are exempt by
  declaration. (The publish-set 87% floor needs all six producers; none of the
  changed files live outside core/server, and the diff gate — the part that scores
  this candidate's own lines — is green.)

## Issue #38 acceptance, focused re-evidence at ea8b8a125

- `packages/maistro-core/tests/projects/test_scope_store_conformance.py` with
  `MAISTRO_REQUIRE_PG_LEGS=1`: **75 passed / 2 skipped** across memory+sqlite+postgres.
  The 2 skips are by-design (postgres FK enforces the owns-runs rule by constraint;
  PG drains a workspace in one pass, so the iterative-purge bound has no failure mode
  there). Includes the #1147 concurrency pair
  (`test_concurrent_opposite_moves_cannot_both_commit_a_cycle`,
  `test_an_unlocked_writer_cannot_collide_with_a_locked_one`) and the #1148 lifecycle
  set (`test_concurrent_membership_writes_leave_exactly_one_row`,
  `test_a_revocation_racing_a_delegated_merge_cannot_resurrect_revoked_grants`,
  `test_revoked_membership_is_gone_and_can_be_re_granted`, pre-1148 in-place upgrade)
  — each on all three backends.
- Run-spine conformance (`runs/test_spine_conformance.py`) with PG legs: **361 passed**
  (fresh-store reopen; historical-Run scope immutability). Combined
  spine+projects+workspaces run: **609 passed / 4 skipped**; one earlier invocation of
  the same combination showed a single `graph_snapshot_survives_the_round_trip[sqlite]`
  error that vanished on immediate re-run of both the isolated test and the whole
  combination — a non-deterministic suite-isolation artifact, absent from the
  CI-shaped full-core run.
- `test_denies_accumulate_and_win_over_descendant_grants`
  (`tests/projects/test_scope.py:254`) green in the projects run.
- Container root wiring + server projects API
  (`test_container_wiring.py`, `test_projects_api.py`): **67 passed**.

## Residual risks

- The publish-set 87% aggregate floor was not re-measured (requires the
  canvas/evolve/turing/design/hive/scripts producers with MinIO); the diff gate that
  scores this candidate's lines is green and no changed file sits outside core/server.
- `test_an_unreachable_server_is_an_error_not_a_fallback` remains a WSL-environment
  flake under the 30s per-test cap (documented here and in
  m1-38-repair-verification-e8c7467a7.md); it passes in isolation and in CI.
