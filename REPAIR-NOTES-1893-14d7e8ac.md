# REPAIR NOTES — issue #1893 round at 14d7e8ac4 (job 955976d8)

## Snapshot processed (frozen at start)

- Assigned: repair of issue #1893 on branch `auto-1893`, worktree
  `/home/dev/Git/wt/auto-1893`, starting head `14d7e8ac4717` (verified exact),
  develop base `ab8b3737` (dispatch) / merge-base `ac737014`.
- Items: (1) lane-named CI gate failure `test: failure`; (2) previous round's
  BLOCKED (reachability provenance). Nothing else.

## Findings and executed evidence

1. **`test: failure` is not this branch's failing gate — proven with live API
   evidence and local re-execution.**
   - Live API at remote head `80171ce1cff9` (`origin/auto-1893`, strict
     ancestor of local HEAD, 39 ahead / 0 behind): workflow `CI` success,
     `quality` success, `Vulture Ratchet` failure; job `exact-debt-ledger`
     (117010602424) failed exactly one step — "Require enforced ratchet
     provenance policy" (`vulture-ratchet.yml:78`). Vulture step did not fail.
   - All seven CI `test` legs re-run green at HEAD 14d7e8ac4 with CI env:
     tests/ 4978+135sk, server 557+8sk, turing 210, turing/backend 90, design
     572+1sk, ext-harness 273, ext-sdk 147.
2. **The real red reproduces locally, CI-exact.**
   - `RATCHET_BASE_REV=origin/develop uv run python
     scripts/check-ratchet-provenance.py` → exit 1 on exactly
     `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`
     ("NEW ... not previously authorized" / "not covered by an already-landed
     reachability authorization").
   - `check-shipped-surface-truth.py` exit 0; `check-vulture-baseline.py
     packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0
     with 1322 reviewed = 1322 findings → **no unbanked vulture identity, so
     the lane brief's permitted `quality/vulture-baseline.json` amendment has
     no target.** The failing ledger is the *reachability* one, which neither
     the lane brief nor the system-prompt exception authorizes editing, and
     the issue explicitly forbids baseline/grant edits to green an unwired
     slice.
   - Candidate-side legs pass: reachability 171 banked exit 0, dispositions
     50 groups exit 0. The provenance wrappers read authorizations from the
     merge-base revision (scripts/ratchet_provenance.py:478-518): a grant
     cannot authorize the change that introduces it (two-merge rule).
3. **B2 acceptance re-proven on fresh infrastructure (not trusted from prior
   rounds).**
   - Fresh disposable PG 18.6 container, DB migrated through the real chain
     `alembic upgrade head` 001→063; `ck_task_idempotency_v2_identity`
     present; focused B2 suites `MAISTRO_REQUIRE_PG_LEGS=1` → **204 passed,
     0 skipped**; `task_idempotency` residue **0 rows**; live CHECK rejection
     demonstrated for `task_id != receipt_id`.
   - Repaired sites verified in code: `admission_codec.py:291-292` emits
     `task_id`/`run_id` together from the binding;
     `admission_identity.py:291-292` enforces
     `binding.receipt_id == envelope.receipt_id`.
   - All 10 prospective issue tests present and executed; mypy maistro-core
     clean; ruff check + format green (driver logs).
   - Full maistro-core tree with PG legs: 16437 passed, 137 skipped, 7
     failed — all 7 pre-existing in approval/backlog conformance PG legs
     (modules untouched by this branch; never run with PG by CI). Zero
     failures in branch-touched code. Environmental footnote: passing
     `postgresql+asyncpg://` in `MAISTRO_TEST_DATABASE_URL` breaks
     `conformance/_legs.py` (it feeds the variable to asyncpg raw); plain
     scheme satisfies both fixture families.
4. **Develop sync considered and deliberately skipped.** `origin/develop`
   advanced one unrelated commit to `ab8b3737` (#1627 graph test); grant
   `3235229f5fed` is still not an ancestor of `origin/develop`. Merging
   develop now would move the trusted base without authorizing the two rows;
   the merge belongs after the grant lands on develop (step two of
   two-merge). No conflict exists to resolve.
5. **No closure keywords** against #1893 in `ac737014..HEAD` commit subjects.

## Structural blocker (unchanged)

`check-ratchet-provenance.py` cannot pass in-branch: the two-merge rule
requires the reachability authorization to land on `origin/develop` first,
which needs a develop-side push — worker-prohibited. Unblock: land grant
`3235229f5fed`'s authorization content on develop, then merge
`origin/develop` into `auto-1893`.

Full evidence: `docs/testing/inventory-notes/atomic-admission-1893-verify-14d7e8ac.md`.
