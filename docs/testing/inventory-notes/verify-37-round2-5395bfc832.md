# Verification round 2 (deep review) — #37 at 5395bfc832 + digest-repair handoff

Round L37 verify #2 (job b60177950b47). Adversarial re-examination of the five
round-1 findings at the exact assigned head `5395bfc832` (worktree clean, no
merge/pull/push performed; the round-1 "develop sync conflict" block is already
resolved in history by `1ef9d9462e` + `c71f575dd0`). One new RED gate found in
live CI and repaired locally (digest pin), plus one confirmed doc-drift finding
handed back to the lane.

## Adjudication of round-1 findings

1. **ADR "migration 069" drift — CONFIRMED (branch-introduced, doc-only).**
   The round-1 rewrite of the ADR Neutral section introduced
   `docs/adr/ADR-092326-97c4-shared-postgres-workspace-owner.md:164`
   ("... foreign key in migration 069"), but the shipped revision is
   `alembic/versions/072_workspace_tombstones_and_project_fk.py:64-65`
   (`revision = "072"`, `down_revision = "071"`); `069_schedule_deletions.py`
   is develop's unrelated migration. The migration's own docstring (lines
   10-16) documents the renumber — only the ADR prose is stale. A reader
   following "069" lands on the wrong file. One-word repair owed by the lane
   owner; not edited in this verify round. The companion claim ("does not by
   itself prove the delete/revoke/Run-admission race") is literally true — the
   FK alone does not — and the race itself IS proven by AC3 tests on real
   pg17 (`test_an_admission_waits_on_a_delete_holding_the_workspace_lock`,
   `test_a_committed_delete_strands_no_root_from_a_racing_admission`), so it
   is understatement, not falsehood.
2. **quality.yml timeout 20->40 benign — HOLDS.** `git diff 618954f052 HEAD --
   .github/workflows/quality.yml` is exactly the `coverage-postgres`
   `timeout-minutes` raise plus comment; no command/gate changed. Stronger
   proof this round: re-digesting the base job with `timeout-minutes: 40`
   yields byte-identical SHA-256 `c0ea11010a48...` to the live job — the
   delta encodes nothing but the ceiling. Live CI confirms: coverage
   (PostgreSQL) **SUCCESS** at this head (run 45959673887, job
   140374366736, completed 07:58:04Z) after the round-1 cancel.
3. **"No completed CI run at head" — REFUTED by fresh evidence.** Runs
   45959673732 (CI) / 45959673887 (quality) at `5395bfc832` completed:
   postgres (pg17) and (pg18), integration-scope, docker-build,
   hive-conductor-e2e, hive-conductor-e2e-ui, strike-ladder, wheel-imports,
   hive-conductor-compose-durability, exact-debt-ledger all **SUCCESS**.
   This upgrades finding 4 (integration legs UNVERIFIED) to CI-verified at
   this head. Still open at capture time: CI `test` job **FAILURE** (item 4
   below), `Coverage gate (publish-set floor + diff coverage)` IN_PROGRESS,
   `gates-ran` PENDING.
4. **NEW red gate found + repaired: CI `test` job digest pin.**
   `tests/test_ci_quality_split.py:43` (reached from
   `test_every_original_quality_obligation_survives_with_its_profile`) pins a
   SHA-256 of the parsed `coverage-postgres` job via
   `tests/fixtures/ci_quality_obligations.json`; the timeout raise changed
   the digest (`d1ed5daf...` -> `c0ea1101...`), failing run 45959673732 job
   140374257237. This suite (`pytest tests/`) was never in the round-1 local
   check set, so it was invisible locally. Repair: one-line fixture update to
   `c0ea11010a48c31c93570da51a2e281f9c446302282d4e3a8f1cd36d078b951e`
   (computed with the test's own algorithm; matches CI's actual). Minimality
   proven: digest(base job + timeout 40) == new digest, so the pin still
   asserts every other job property (steps, services, env, commands).
   Local proof at gate scope: `uv run pytest tests/ --ignore=tests/tools/
   registry -q` -> **6393 passed, 141 skipped** (8m51s), matching CI's
   6392+1 exactly, now all green. This is acknowledgment of a documented
   capacity raise, the mechanism's designed path (#2528 precedent), not gate
   weakening.
5. **AC6 (#1419 evidence map) open — HOLDS.** ADR lines 158-166 still record
   the joint #1419 representation-purpose audit as open; issue-level
   acceptance cannot be proven from this PR.

## Ledger integrity after the develop sync

`git diff --numstat origin/develop -- quality/` shows only
`25 0 quality/durable-table-retention.json` — additions, zero deletions; no
merge-lost rows. Live `exact-debt-ledger` SUCCESS at this head corroborates.

## Handoff

- One-word ADR repair: "migration 069" -> "migration 072" at ADR line 164.
- Fresh CI run required at the digest-repair commit: CI `test` job must flip
  green; `Coverage gate` and `gates-ran` were pending at capture.
- Nothing else changed: no production code touched this round.
