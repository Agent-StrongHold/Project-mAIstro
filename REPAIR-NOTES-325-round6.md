# Issue #325 repair round 6 — salvage commit, purge-order regression test, format repair

Starting head `abf89c5d7` with one uncommitted change (salvaged, backed up to
`../incoming-325.patch` before touching anything): `SqliteAuditLog.log` now
stores the signed entry's timestamp normalized to UTC. `purge_expired` deletes
with a lexical `timestamp < ?` against a UTC ISO cutoff, so a caller-supplied
non-UTC aware `AuditEntry.timestamp` (the dataclass accepts any tz-aware
datetime; the default is `now(UTC)`) sorted literally younger than its true
instant — `09:00-05:00` (= 14:00 UTC) sorts before a `13:00+00:00` cutoff and
would be purged five hours early. The fix matches the convention
`sqlite_outcomes.py:527` and `sqlite_learnings.py:928` already apply. Signature
verification is untouched: `timestamp` is in `_CANONICAL_METADATA_FIELDS`
(`security/sentinel/signing.py`), so the proof never covered it.

## Changes

1. `packages/maistro-core/src/maistro/persistence/sqlite_audit.py` — the
   salvaged fix, committed (byte-identical to the backup patch; verified by
   diffing `^[+-]` lines of both patches).
2. `packages/maistro-core/tests/persistence/test_sqlite_audit.py` — new
   regression test `test_a_non_utc_entry_timestamp_is_stored_as_a_utc_instant`:
   a `09:00-05:00` entry is stored as `14:00:00+00:00`, round-trips to the
   same instant and verifies, survives a 13:00 UTC purge cutoff, is removed by
   a 15:00 UTC cutoff. Proven to name the regression: with the fix temporarily
   reverted the test fails on the stored-text assert (and the 13:00 cutoff
   would lexically delete the row); with the fix restored all 23 file tests
   pass.
3. `docs/testing/inventory-notes/auto-325-utc-audit-timestamp.md` —
   `inventory-delta: packages/maistro-core/tests: +1`.
4. `packages/maistro-core/src/maistro/runs/pg_store.py` — one-line reformat:
   `ruff format --check` flagged the `to_regclass` fetchval line from the
   round-5 head commit `abf89c5d7` (89-char line over the limit). Pure
   formatting, verified by diffing before/after (single statement split across
   lines).

## Commands run this round (all green)

- `uv run ruff check .` -> All checks passed
- `uv run ruff format --check .` -> 3537 files already formatted (after fix 4)
- `uv run pytest packages/maistro-core/tests/persistence/test_sqlite_audit.py -q`
  -> 23 passed; single new test -> FAILED against reverted fix, PASSED with fix
- `uv run pytest` (events/persistence/quota/observability/tasks/security/
  workspaces suites) -> 412 passed, 83 skipped
- `uv run pytest` (runs retention suites + eval-on-run internals) -> 123
  passed, 30 skipped
- `uv run pytest packages/maistro-turing/backend/tests/test_chat.py -q` -> 31 passed
- `uv run python3 scripts/check-durable-table-inventory.py` (CI's exact
  invocation, `ci.yml:253`) -> ok: 123 durable tables, each with a declared retention
- `uv run python scripts/check-suite-inventory.py` (CI's exact invocation) ->
  ok: 21 suite(s) match the recorded inventory (includes the +1 delta)
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact invocation) ->
  1255/1255, exit 0
- `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src
  packages/maistro-ext-sdk/src` (AGENTS.md/CI command) -> Success: no issues
  found in 944 source files

## Residuals (recorded, not silently dropped)

- **Gate C (canonical clean install) was cancelled in CI, not failed.** A
  cancellation carries no code evidence; locally it cannot be reproduced
  because ports 8000/8101 are already held by another running stack that this
  lane must not disturb (and `.maistro-install` is untracked, so a local run
  would dirty the worktree). The durable-table inventory, suite inventory,
  vulture ledger, mypy, and ruff gates all pass at this head with CI's exact
  arguments.
- **Coverage-gate "Event loop is closed" findings at merge-group 013b6a0:**
  not reproducible locally — the full events/persistence battery runs clean at
  this head with no teardown errors; the CI log excerpt identifies no failing
  test name, and the prior merge-queue evaluation was green (round-5 notes).
  Left to CI re-evaluation rather than guessed at.
- **origin/develop moved 4 commits ahead** (incl. #2287, which touches durable
  tables, and quality-ledger edits incl. `vulture-baseline.json` −7 rows). The
  stated previous block was a provider timeout, not a develop conflict, so the
  brief's merge instruction does not fire; a mid-round merge would risk the
  quality-ledger row-loss hazard AGENTS.md documents. Next sync round must
  `git merge origin/develop`, resolve in place, re-count `quality/*.json` rows
  against `origin/develop`, and re-run `check-durable-table-inventory.py` for
  any tables #2287 adds.
