---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair validation — 94867743

## Scope and disposition

**BLOCKED.** Assigned branch/worktree `auto-1893`, starting source
`3402034333c08aff8ce5ed7d3168e05fadbafb9b`, supplied develop base
`1c886750c2d547b47fff905954e33006b8c93f29`. The initial worktree was clean.
This round changes only this evidence note, with no tests added, source changes,
ledger amendments, grant edits, activation, or GitHub mutations.

The supplied binding finding is stale: `admission_codec.py:290` already encodes
`task_id` from the bound receipt, matching migration 055's paired-column and
receipt-equality constraint. Fresh unit, database and mutation checks below
confirm that repair. The exact requested vulture scan passes; there are no
unbanked identities to review or removed identities to delete, so changing its
ledger would not address evidence.

The actual reproduced blocker is **trusted-base reachability/disposition
provenance**, not vulture debt. Both `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` add unauthorized unreachable modules and
candidate dispositions. The supplied base resolves, but its merge base with
this branch is `66f3cea9e98980f146a12cf3142d66e30986d276`, which the gate correctly
uses as the trusted baseline. No merge conflict exists. The hosted `test:
failure` has no supplied failing traceback and was not reproduced by the
changed-package suite; full hosted CI is not certified.

Read repository instructions, supplied issue body/recent comments/PR review
findings, previous result, driver `check-0.log` through `check-4.log`, migration
055, adjacent types/tests and accepted ADRs 081426-1f7c, 082526-7f02,
082826-b601 and 082826-d9f5. Reconciliation: this staged B2 codec neither
creates an execution authority nor activates an admission path. Its no-consumer
status cannot be repaired by inventing a caller solely to satisfy reachability.
The assignment permits only a vulture ledger exception, not authorization or
reachability ledger changes. Coordinating the real consumer/integration base
or separately landed authorization requires owner action outside this repair.

## Executed validation

All commands ran against the starting source above. Detailed logs, full
collected node IDs and JUnit properties are retained in
`/home/dev/maistro/jobs/94867743c1774dfaaeaf1f8ac1bff5fc/`.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  **201 passed, 3 skipped** (`worker-focused.log`). Skips are not DB evidence.
- Created a fresh dedicated disposable local PostgreSQL DB
  `maistro_1893_94867743`. `DATABASE_URL=postgresql:///maistro_1893_94867743
  uv run alembic upgrade head`: **passed**, actual empty-to-head chain through
  **061**, including 055 (`worker-migrate.log`). No mocked/SQLite schema and
  no downgrade tests.
- Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_94867743`, `MAISTRO_REQUIRE_PG_LEGS=1`, focused
  command above plus `-o junit_family=legacy
  --junitxml=<job>/worker-focused-pg.xml`: **204 passed, zero skips**.
  Non-null production-codec pool and independent raw pool connected to that
  same DB over the local socket. Production/raw backend PID pairs were
  **230606/230607** (unbound), **230608/230609** (bound), **230615/230617**
  (acknowledged). Each verified exactly **one persisted scoped admission row**,
  identical TEXT mappings, exact record round trips and rejection of corrupt
  surrogate TEXT in each snapshot column through both pools. Each cleaned
  its scoped row. Final SQL revision **061**; admission rows / distinct
  generations / distinct bound Run IDs **0 / 0 / 0** (`worker-db-counts.log`).
- Existing regression sensitivity: process-local wrapper around the encoder
  forced `task_id=None` while keeping `run_id`; `pytest.main` with
  `-k test_v2_round_trip_preserves_all_snapshot_bytes` produced **2 failed,
  1 passed, 128 deselected**. Both bound states failed the independent storage
  assertion at `test_admission_codec.py:134`, `None != 'rcpt-1'`
  (`worker-binding-mutation.log`). No source file was mutated. This is
  sensitivity evidence for the already-fixed defect, not a new repair claim.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: **14789 passed, 1004 skipped, 1 xfailed,
  53 warnings**, 233.01 seconds (`worker-core.log`). This broader run had no
  DB environment; its skips are not durability proof. Warnings include a
  pre-existing unawaited fake-process coroutine; no failure was reproduced.
- Focused `--collect-only -q`: **204 nodes** (`worker-nodes.log`).
  `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **passed**, **15794 nodes**, zero duplicate
  evidence (`worker-inventory.log`).
- `uv run ruff check .`: **passed** (`worker-ruff.log`).
  `uv run ruff format --check .`: **passed**, 3177 files (`worker-format.log`).
  `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **passed**
  (`worker-mypy.log`).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, **1326 reviewed
  identities / 1326 findings** (`worker-vulture.log`). No amendment warranted.
- `uv run python scripts/check-<name>.py`, for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: **passed**
  (`worker-<name>.log`). Candidate-local reachability/disposition success
  does not grant trusted-base authorization.
- `RATCHET_BASE_REV=1c886750c2d547b47fff905954e33006b8c93f29 uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**, exit 1
  (`worker-provenance.log`), specifically the two modules' unauthorized new
  reachability and dispositions. Other provenance subchecks passed.

## Acceptance and limitations

The ten named prospective codec tests all executed: v2 snapshot round trips,
UUID hex storage/token redaction, distinct legacy binding shapes, expiry
header without invented identity, header preservation across malformed
snapshot/partial binding failures, unknown-format rejection, tagged nonfinite
fingerprint preservation, malformed/duplicate JSON rejection and real
raw/production TEXT-pool contrast. Existing additional tests exercise scalar
mismatch/range, incomplete schemas, numeric precision rejection, Unicode
corruption and partial/mismatched v2 binding. Source inspection confirms
frozen/slotted headers, no clock/request-fingerprint input, no fingerprint
recomputation, no assessment/claim choice or SQL mutation in the codec.

These prove the **codec/storage boundary**, not reachable admission behavior.
Production import search finds no codec consumer; `admission_codec.py:51`
and `admission_identity.py:3` explicitly describe staged/inactive contracts.
Synthetic strings in the DB fixture are not authorized principals,
Workspace/Project or registered Graph admission. **UNVERIFIED**: reachable
production integration, authorization, end-to-end evidence model materialization
with `model_of`/`model_of_json`, actual Run JSONB object insertion, live expiry/
409 precedence, dependency constructor normalization before encoding, production
activation and full required hosted CI. This round does not resolve these by
expanding the assigned codec leaf.

Handoff: obtain the hosted failing test traceback and coordinate the trusted
integration/consumer or pre-landed authorization. Do not repeat a vulture-only
repair without new evidence: its named scan is already green and cannot resolve
the reproduced provenance failure. Progress: checked **1**, done **0 repairs**
(revalidation complete), skipped **0 issues**, errors **1 gate**. Evidence is
committed locally; no merge or activation readiness is asserted.
