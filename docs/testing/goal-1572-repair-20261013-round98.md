# Goal #1572 repair — round 98 (2026-10-13)

Branch `auto-1572` at `332c24c54a` + this round. Repairs the two findings from
the previous verification round at that head. Docs-only-delta claim: **false**
— one production defect fixed, three tests added (inventory delta +9, see
`docs/testing/inventory-notes/issue-1572-goal-reassign-cas.md`).

## Finding 1 — concurrent `reassign_agent` both landing on PostgreSQL

`pg_store.py`'s guarded UPDATEs guarded only `current_revision` and
`status = 'active'`, but a reassignment moves neither — ownership is recorded,
not versioned — and every mutation writes the whole-row payload built from its
read. Three consequences, all fixed by carrying the owner as read (`agent_id =
$6` / `AND agent_id = ?`) in **all three** guarded UPDATEs of `pg_store.py`
and `sqlite_store.py`:

- two concurrent `reassign_agent` calls from one revision both landed, the
  second recording a `from_agent_id` the row no longer held at write time;
- an append or transition whose read predated a landed reassignment wrote the
  stale owner back over the row through the payload;
- zero rows now means exactly one thing on every mutation: the Goal moved
  between the read and the write (revision, terminal state, or owner), which
  is the one refusal `GoalRevisionConflict` documents.

The reference `InMemoryGoalStore` needs no owner arm: its read is atomic with
its write under the store lock, so its guard is already its full read
pre-image, and its records are true by construction. Protocol and module
docstrings in `store.py` now state this division explicitly.

## Finding 2 — `git diff --check` exits 2

`docs/testing/goal-1572-repair-20261012-round59.md:47` (trailing whitespace)
and `docs/testing/issue-1572-repair-checkpoint.md:191` (blank line at EOF)
repaired in place; content otherwise untouched. `git diff --check
3c761d14..HEAD` exits 0 at this round's commit.

## Tests (red first, then green)

`test_goal_store_conformance.py` gains the owner-guard legs, parametrized over
all three backends (+9 collected nodes):

- `test_concurrent_reassignments_record_truthful_ownership` — the recorded
  chain (creation owner → each record) ends exactly at the row's owner.
- `test_a_reassignment_that_read_before_another_writer_landed_is_refused` —
  deterministic race: the caller's read is held open (hooking the read path
  each backend's mutation actually uses) while a complete out-of-band
  reassignment commits; the write must refuse, record nothing, and a fresh
  read must re-derive with a true record.
- `test_an_append_that_read_before_a_reassignment_landed_is_refused` — the
  stale-payload clobber: the append refuses and the landed reassignment
  survives.

Red evidence: the three tests run against the pre-fix stores at `332c24c54`
(thrown-away worktree, `goals_r1572b` pg18 on :15497): **5 failed** —
reassign refusal missing on sqlite+postgres, stale append rewriting the owner
on sqlite+postgres, PG audit-truth lie — 2 structural memory skips. Green at
this round's tree: **7 passed, 2 skipped**.

## Battery executed at this round's tree

- `uv run pytest packages/maistro-core/tests -q` → **15269 passed, 1072
  skipped, 3 xfailed, 0 failed**. (One earlier run showed 5 failures + 760
  fixture errors that were a transient host tmpfs exhaustion — ENOSPC on
  `/tmp` — not code; the rerun above is clean.)
- Goals suite with enforced PG legs (`MAISTRO_REQUIRE_PG_LEGS=1`,
  pg18 `goals_r1572b`) → 78 passed, 2 skipped (the structural skips).
- Driver's targeted battery (events/extensions/goals/workspaces list) with PG
  legs → 197 passed, 2 skipped.
- `uv run ruff check .` → all passed; `uv run ruff format --check .` → 3288
  files already formatted.
- `uv run mypy packages/maistro-core/src` → the 5 pre-existing
  `maistro_bootstrap` import-not-found errors only (byte-identical at HEAD);
  no new errors.
- `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` → ok
  (+9 delta recorded in the note named above).
- `scripts/check-execution-lifecycles.py` → exit 0 (19/19 classified).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0, 1323 = 1323; no amendment made.
- `scripts/check-m1-convergence-freeze.py --base 3c761d14db94` → exit 0.
- Alembic on pg18: `downgrade 062` drops the three Goal tables; `upgrade head`
  recreates them (verified by catalogue query).

## Not executed here

PostgreSQL 17 legs (the pg17 matrix job owns them); the full Hive /
maistro-server product compositions (the wiring suite holds the composition
seams; prior rounds' verdict on executing both products stands).
