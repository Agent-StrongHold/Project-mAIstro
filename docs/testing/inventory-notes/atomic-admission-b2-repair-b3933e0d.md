---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair round — job b3933e0d (independent re-validation at d7ee027; sole residual remains the external two-merge grant)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`d7ee0272131e13c35c6940808fdf67e76927d672` (exact dispatch head). This
round authors no production code, no tests, no ledger rows, no grants
and no gate files; the only tree change is this note. Nothing was
trusted from earlier rounds: every gate, suite and database probe below
was executed fresh in this round at this head.

## Dispatched CI failure `test:` — re-proven green at this head

The dispatched check-run snapshot (`commits/e519c6dfcf41…/check-runs`,
the CI-evaluated head) shows the `test` job **completed / success**;
every commit since is docs-only (`git diff e519c6df..HEAD` = one
inventory-note .md, 0 non-markdown files), so all npm/OpenAPI legs
carry. Every Python leg of the `test` job re-executed fresh at
d7ee027 under the CI job's environment (`REQUIRE_AUTH=false
MAISTRO_DRY_RUN=1`):

- `packages/maistro-server/tests`: **557 passed, 8 skipped**
- `packages/maistro-turing/tests`: **210 passed**;
  `maistro-turing/backend/tests`: **90 passed**
- `packages/maistro-design/tests`: **572 passed, 1 skipped**
- `packages/maistro-ext-harness/tests`: **273 passed**
- `packages/maistro-ext-sdk/tests`: **147 passed**
- `tests/ --ignore=tests/tools/registry`: **4971 passed, 129 skipped**
- `packages/hive-conductor/backend/tests`: **3626 passed, 19 skipped**
- cross-suite leakage (one process, `--timeout=60`): **9262 passed,
  149 skipped**
- `scripts/check-suite-inventory.py`: **ok, 17 suite(s) match the
  recorded inventory**; `scripts/check-test-duplicates.py`: 1589 files,
  0 duplicate groups, ok
- `uv run ruff check .` clean; `ruff format --check .` 3277 files clean;
  AGENTS.md publish-set `uv run mypy …`: **Success, no issues in 894
  source files**
- driver pre-checks at this head (job check-*.log): uv sync, ruff
  check/format, focused admission suites 201 passed 3 skipped,
  maistro-core suite inventory ok

## Issue #1893 acceptance — re-proven from source and live database

Named source repairs re-read at this head (not from prior claims):

- `admission_codec.py` `encode_admission_record` emits
  `task_id = binding.receipt_id` and `run_id = binding.run_id`
  together from the binding (both NULL unbound).
- `admission_identity.py` `AdmissionRecordV2.__post_init__` enforces
  `binding.receipt_id == envelope.receipt_id` and refuses
  `acknowledged_at_us` without an existing binding.
- `test_admission_codec.py::test_v2_round_trip_preserves_all_snapshot_bytes`
  asserts the migration-055 storage contract independently of
  encode/decode agreement.

Live durability, fresh disposable database `maistro_1893_r5` in the
`auto-1893-pg` (pgvector/pgvector:pg18) container: real chain
`uv run alembic upgrade head` 001 → `062 (head)`; focused admission
suites with `MAISTRO_REQUIRE_PG_LEGS=1` and both `MAISTRO_TEST_PG_DSN`
and `MAISTRO_TEST_DATABASE_URL` on that DB: **204 passed, 0 skipped**.
Fresh asyncpg probes at the migrated schema:

- `pg_get_constraintdef('ck_task_idempotency_v2_identity')` carries the
  055 binding and acknowledgement clauses verbatim (pg-normalized
  parentheses).
- INSERT of the production encoder's exact row (bound + acknowledged)
  ACCEPTED.
- INSERTs with `task_id ≠ receipt_id`, `run_id` without `task_id`,
  `task_id` without `run_id`, and acknowledged-without-pair each
  REJECTED by `ck_task_idempotency_v2_identity`
  (`asyncpg.exceptions.CheckViolationError`, constraint named).
  (The DTO layer independently refuses the ack-without-binding
  construction at `admission_identity.py`, so that probe drives the raw
  row a buggy writer would send.)
- Probed rows deleted; **0 residue rows**.

Scope versus develop re-checked by name-status: only
`maistro/runs/admission_identity.py`, `maistro/tasks/admission_codec.py`,
`_vulture_whitelist.py`, the two test files, the quality reachability
rows (+2 baseline / +11 disposition lines) and docs — no SQL mutation,
no HTTP mapping, no queue change, no OpenAPI surface.

## exact-debt-ledger — the one red gate, unchanged and external

CI-exact invocations re-run this round:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323
  reviewed identities = 1323 findings, `unclassified: 0`. Zero unbanked
  identities, so the CI-repair allowance to amend
  `quality/vulture-baseline.json` has nothing to act on; no amendment
  was made and none was needed.
- `uv run python scripts/check-ratchet-provenance.py` (with
  `RATCHET_BASE_REV=origin/develop`) → exit 1; the only failing
  sub-ratchets are reachability and reachability-dispositions, solely
  for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` ("NEW unreachable module absent from
  trusted base and not previously authorized" x2 / "NEW disposition
  absent from trusted ledger" x2). Shell-execution, contract-markers,
  enumerations, lifecycle, promotion and contradiction sub-ratchets all
  OK.
- Candidate-side gates both pass at this head:
  `scripts/check-reachability.py` (1396 modules, 171 unreachable —
  ledger matches scan) and `scripts/check-reachability-dispositions.py`
  (50 groups disposition all 171: 149 CONNECT, 20 LIBRARY, 2 RETIRE).
- `scripts/check-shipped-surface-truth.py` → exit 0.

Origin re-fetched this round: `origin/develop` is still `435dc193`
(merge-base of HEAD, so there is no develop-sync conflict to resolve)
and carries **0** admission authorization rows. The two-merge rule
therefore still applies: provenance reads authorizations from the merge
base, which authorizes nothing for these modules, while issue #1893
explicitly forbids baseline/grant/gate modifications that would green an
unwired slice from the candidate side. The documented resolution is
unchanged and external to this branch: land the reachability
authorization on develop first, then merge develop into `auto-1893`.
No in-lane repair exists without violating the issue or the ratchet's
own provenance policy.

## Verdict

Every in-branch acceptance criterion of #1893 is independently re-proven
at this head, and the dispatched `test:` failure does not exist at this
content (CI success captured at the CI-evaluated SHA; every Python leg
re-executed green with baseline-identical counts). The sole red is
exact-debt-ledger's reachability provenance, structurally unfixable
in-lane by the two-merge rule while `origin/develop` carries zero
authorization rows — external owner action (land the grant on develop),
then merge develop into this branch. This round makes no gate, ledger,
grant or production edits.
