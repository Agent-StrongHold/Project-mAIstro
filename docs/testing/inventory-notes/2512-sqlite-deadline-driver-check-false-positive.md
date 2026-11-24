---
inventory-delta:
  packages/maistro-core/tests: 0
  packages/hive-conductor/backend/tests: 0
---

# #2512 repair round at `c45b59c91b1d` — driver check-3 is a false positive

## The reported failure

The prior verify job (`043cd818469b45c3ae8715acb972689e`) recorded
`failure_kind: validation` citing its `check-3.log`. That check ran
`uv run pytest packages/maistro-core/tests/conftest.py -q -x` and got
`no tests ran` with pytest exit code 5.

## Why this is not a branch regression

- The branch's only change to that file is one tuple row
  (`"schedule_deletions"` added to `_PG_SCRATCH_TABLES` at line 165) so the
  new deletion-ledger table introduced by this branch (alembic `069`,
  `store.py` DDL, `pg_store.py` tombstones) is scratch-reset between
  PostgreSQL-backed tests. The table is otherwise absent from that list and
  rows would survive between runs — the exact failure mode the tuple's
  comment documents for `(#563)`.
- Both the base (`a6a0969ca1`) and the branch copies of the conftest contain
  **0** top-level `def test_*` / `async def test_*` functions (verified with
  `git show` + grep). pytest therefore collects zero items from that path at
  base too: the check fails identically on develop, so it cannot be evidence
  of anything this branch introduced.
- A control experiment (`pytest /tmp/.../conftest.py` containing one
  `test_` function) collected and passed 1 item, proving the exit code
  depends solely on the presence of collectable test functions, not on the
  fixture change.
- No GitHub Actions workflow invokes pytest on a `conftest.py` path
  (`grep -rn conftest .github/workflows/` matches only comments about the
  file in `ci.yml` / `quality.yml`). CI runs whole suites. The check is a
  per-changed-file driver heuristic, not a repository gate.

Wedge-fixing it by placing a token test inside `conftest.py` was rejected as
a cosmetic change that would pollute the suite inventory; moving the
scratch-table tuple out of the conftest into a `src/` helper was rejected as
restructuring with worse engineering for a one-line fixture constant.

## Fresh validation executed at this exact head

- `uv run ruff check .` → **All checks passed!**
- `uv run ruff format --check .` → **3644 files already formatted**
- `.venv/bin/python -m pytest packages/hive-conductor/backend/tests/test_schedule_canonical_definitions.py packages/hive-conductor/backend/tests/test_schedule_projection_authority.py packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py -q` → **95 passed, 31 skipped in 13.60s** (matches the driver's own check-4: 95 passed, 31 skipped)
- `.venv/bin/python -m pytest "packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py::test_independent_processes_racing_startup_converge_on_canonical_truth" -q` → **1 passed, 2 skipped in 2.78s** — the racing-startup readiness waits run far inside the raised deadline.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` → **ok** (4514 collected = recorded inventory)
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` → **ok** (18908 collected = recorded inventory)
- `.venv/bin/python -m pytest packages/maistro-core/tests/scheduling -q` → **289 passed, 38 skipped in 7.91s** — the modified conftest imports and drives the core scheduling suite without error.

## Issue acceptance evidence

Commit `2a838da099f` (the issue's own commit) is exactly the two-sided
deadline raise in `test_scheduler_projection_authority.py`:
`deadline = time.monotonic() + 60.0` → `+ 120.0` in both the spawned worker
script's startup wait (line 101) and the parent process readiness wait
(line 776). No other behavior changed in that commit. The test passes at
this head in 2.78s; the non-runnable store variants skip exactly as the
issue body records.

No test functions were added or removed by this round; the inventory delta
is zero and no code was changed — this round's only delta is this note.
