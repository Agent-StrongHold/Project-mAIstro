---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair verification round: codec defect closed, provenance gate external

## Frozen scope and reconciliation

This round processes only issue #1893 in `auto-1893`, starting at the assigned
head `feb983e489a5c2826a93766b419776b9549cf4d7` against develop base
`0d49d4e068de9ecbf0f9510e33781dba8abc87de`. The worktree was clean at entry.
Only this inventory note changes in this round; no production or test code is
edited. The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model and
the immutable admission provenance ADRs (081426-1f7c, 082526-7f02,
082826-b601, 082826-d9f5) are untouched: the codec stays a pure decode/encode
contract leaf with no production consumer, no clock, no claim mutation and no
HTTP/queue/SQL-mutation surface.

Prior findings were rechecked against the starting source instead of being
trusted:

1. "codec emits `task_id=None` while preserving a bound `run_id`" — already
   repaired. `encode_admission_record` writes `task_id` and `run_id` together
   from the binding (`task_id = binding.receipt_id`, `run_id = binding.run_id`,
   both NULL when unbound); `AdmissionRecordV2.__post_init__` rejects a
   binding whose `receipt_id` differs from the envelope's, and the v2 decoder
   rejects one-sided pairs and `task_id != receipt_id` before dropping the
   bookkeeping id. This is exactly migration 055's v2 CHECK shape
   (`(task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND run_id
   IS NOT NULL AND task_id = receipt_id)`).
2. "test accepts the invalid bound encode/decode mapping" — already repaired:
   `test_v2_round_trip_preserves_all_snapshot_bytes` asserts the storage
   contract structurally (`row["task_id"] == "rcpt-1"` exactly when a binding
   exists) independently of encode/decode agreement.
3. Ratchet provenance — reproduced, and it is structural, not a code defect
   (see below).

## Executed validation (this worktree, this head)

- `uv sync --locked --extra dev`: resolved 256 packages (driver check-0).
- `uv run ruff check .`: all checks passed (driver check-1; re-confirmed on
  the four changed Python paths).
- `uv run ruff format --check .`: 3236 files already formatted (driver
  check-2).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: success, no
  issues in 2 source files.
- Disposable PostgreSQL 18.6 database `maistro_1893_r2` created locally and
  migrated through the real chain: `DATABASE_URL=postgresql:///maistro_1893_r2
  uv run alembic upgrade head` ran 001→061 to head.
- Focused suites with `MAISTRO_TEST_PG_DSN=MAISTRO_TEST_DATABASE_URL=
  postgresql:///maistro_1893_r2` and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` —
  **204 passed, 0 skipped**, including the three
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots` legs
  (raw asyncpg pool vs production `_register_json_codecs` pool, same migrated
  DB, distinct backend PIDs, one persisted row per leg, cleanup verified).
  All ten prospective B2 tests are present and pass.
- Adjacent regression: same DB env, `uv run pytest
  packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -q` —
  **2215 passed, 3 skipped**. Final SQL state: 3 rows, all `format_version=1`
  (adjacent legacy test residue), 0 non-NULL `generation_id`, 2 distinct
  non-NULL `run_id` — no v2 codec residue.
- Root integration suite: `RATCHET_BASE_REV=origin/develop uv run pytest
  tests/ --ignore=tests/tools/registry -q` — **4951 passed, 128 skipped**.
- CI-exact vulture ledger: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0,
  1323 reviewed identities = 1323 findings. **No vulture ledger amendment is
  needed or made**: the scan banks exactly what the ledger records.
- `uv run python scripts/check-reachability.py` — exit 0 (171 unreachable of
  1379 modules, both new modules banked by the branch's ledger rows).
- Suite inventory (driver check-4): ok, `packages/maistro-core/tests: 16246`
  matches the recorded inventory; this round adds no tests (delta 0).

## Remaining blocker: trusted-base reachability provenance (external)

`RATCHET_BASE_REV=origin/develop uv run python
scripts/check-ratchet-provenance.py` exits 1:

- `ratchet: reachability-dispositions` and `ratchet: reachability` both fail
  with "NEW unreachable module / disposition absent from trusted ledger and
  not covered by an already-landed reachability authorization" for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.

This is the documented two-merge rule, not a repairable code fault:
`ratchet_provenance.load_authorizations` reads
`quality/ratchet-authorizations.json` **from the merge base**, so no edit on
this branch can authorize the debt it introduces. `origin/develop`
(0d49d4e06) contains no reachability authorization for these two modules.
Removing the branch's `quality/reachability-baseline.json` /
`reachability-dispositions.json` rows would instead fail
`check-reachability.py` (two new unreachable modules, unbanked); making the
modules reachable would require the production activation and consumer wiring
that #1893's scope explicitly forbids ("Test imports, fake callers and
package exports are not runtime reachability; no baseline/grant/gate
modifications to make an unwired slice green").

Resolution path (owner/campaign action, outside an implementation worker's
authority): land the reachability/disposition authorization grant for the two
modules on develop first, then merge develop into `auto-1893` so the merge
base carries the grant, and re-run the gate. The named CI `test: failure`
could not be reproduced at this head — the full root suite passes locally.

Nothing in this round weakens a gate, edits a grant, or claims integration
approval. Independent mergeability remains blocked on the authorization flow
above.
