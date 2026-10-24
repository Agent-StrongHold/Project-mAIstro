---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair round — job ba0621d6 (independent re-validation at 4f752818; sole residual remains the external two-merge grant)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`4f75281897d1faffa73918a9044f7df68b92443c` (exact dispatch head). This
round authors no production code, no tests, no ledger rows, no grants
and no gate files; the only tree change is this note. Nothing was
trusted from earlier rounds: every gate, suite and database probe below
was executed fresh in this round at this head.

## Dispatched CI failures — live check-run evidence re-read this round

`gh pr view 1945 --json statusCheckRollup` (read-only) at the
CI-evaluated head `e519c6dfcf41…` shows **every required check passing
except `exact-debt-ledger`**: `test` = success (20m58s), `gates-ran` =
"All required checks executed on this exact head", plus lint/typecheck,
postgres pg17/pg18, strike-ladder, e2e, coverage gates, docker-build,
wheel-imports all green (durable-events and MinIO skip as service-gated,
as in CI). `gh run list --branch auto-1893` filtered to failures across
the last 100 runs (2026-10-08 → 2026-10-10) lists **only `Vulture
Ratchet`** — the dispatched `test: failure` does not exist anywhere in
recent CI history on this branch. The exact-debt-ledger job log
(run 38081695521, job 114299758630, merge-ref candidate `eab9b224b490`)
fails inside `check-ratchet-provenance.py` solely on
reachability/reachability-dispositions for the two admission modules —
the vulture sub-ratchet inside the same job passes.

`git diff --name-status e519c6dfcf41..HEAD` = two
`docs/testing/inventory-notes/*.md` files and nothing else, so every
npm/OpenAPI leg of the `test` job carries from the CI-green SHA.

## `test` job Python legs — re-executed fresh at 4f752818

Under the CI job's environment (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`
for the leakage leg):

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
  recorded inventory**; `scripts/check-test-duplicates.py`: 0 duplicate
  groups, ok
- `uv run ruff check .` clean; `ruff format --check .` 3277 files clean;
  AGENTS.md publish-set `uv run mypy …`: **Success, no issues in 894
  source files**

## Issue #1893 acceptance — re-proven from source and live database

Named source repairs re-read at this head:

- `admission_codec.py` `encode_admission_record` emits
  `task_id = binding.receipt_id` and `run_id = binding.run_id`
  together from the binding (both NULL unbound).
- `admission_identity.py` `AdmissionRecordV2.__post_init__` enforces
  `binding.receipt_id == envelope.receipt_id` and refuses
  `acknowledged_at_us` without an existing binding.
- `test_admission_codec.py::test_v2_round_trip_preserves_all_snapshot_bytes`
  pins the migration-055 storage contract independently of
  encode/decode agreement; all ten prospective tests named in the issue
  body exist in the file (one grep hit each).

All six B2 interfaces present as specified
(`AdmissionRowHeader` frozen+slotted, `decode_admission_header`,
`decode_admission_record`, `encode_admission_record`,
`AdmissionDecodeCode` with the six StrEnum values, `AdmissionRowDecodeError`
whose `scope_key` travels only after lowercase-hex validation and whose
raisers suppress parsing chains).

Live durability, fresh disposable database `maistro_1893_r6` in the
`auto-1893-pg` (pgvector/pgvector:pg18, host port 15498) container: real
chain `uv run alembic upgrade head` 001 → `062 (head)`; focused
admission suites with `MAISTRO_REQUIRE_PG_LEGS=1` and both
`MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` on that DB:
**204 passed, 0 skipped**. (A first attempt printed "3 failed" — that
was this round's own shell bug, `export A=x B="$A"` expanding `$A`
before assignment in the driver shell, leaving the DSN vars empty; with
the vars actually set the suites pass 204/0.)

Fresh asyncpg probes (script `/home/dev/admission_probe_r6.py`) at the
migrated schema:

- `pg_get_constraintdef('ck_task_idempotency_v2_identity')` carries the
  055 binding and acknowledgement clauses verbatim (matched on a
  paren-normalized projection: `task_id IS NULL AND run_id IS NULL`,
  `task_id IS NOT NULL AND run_id IS NOT NULL AND task_id = receipt_id`,
  `acknowledged_at IS NULL OR task_id IS NOT NULL AND run_id IS NOT NULL`).
- INSERT of the production shape (bound + acknowledged) ACCEPTED.
- INSERTs with `task_id ≠ receipt_id`, `run_id` without `task_id`,
  `task_id` without `run_id`, and acknowledged-without-pair each
  REJECTED by `ck_task_idempotency_v2_identity`
  (`asyncpg.exceptions.CheckViolationError`, constraint named).
- Probed row deleted; **0 residue rows**.

Scope versus develop re-checked by name-status: only
`maistro/runs/admission_identity.py`, `maistro/tasks/admission_codec.py`,
`_vulture_whitelist.py`, the two test files, the quality reachability
banking rows and docs — no SQL mutation, no HTTP mapping, no queue
change, no OpenAPI surface, and `quality/ratchet-authorizations.json`
untouched.

## exact-debt-ledger — the one red gate, unchanged and external

CI-exact invocations re-run this round:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323
  reviewed identities = 1323 findings, `unclassified: 0`. Zero unbanked
  identities, so this CI-repair round's allowance to amend
  `quality/vulture-baseline.json` has nothing to act on; no amendment
  was made and none was needed.
- `uv run python scripts/check-ratchet-provenance.py` (with
  `RATCHET_BASE_REV=origin/develop`) → **exit 1**, reproducing CI's
  failure byte-for-byte: the only failing sub-ratchets are reachability
  and reachability-dispositions, solely for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
  ("NEW unreachable module absent from trusted base and not previously
  authorized" x2 / "NEW disposition absent from trusted ledger" x2).
  Shell-execution, contract-markers, enumerations, lifecycle, promotion,
  citation, contradiction and ADR-language sub-ratchets all OK.
- Candidate-side gates both pass at this head:
  `scripts/check-reachability.py` (1396 modules, 171 unreachable —
  ledger matches scan) and `scripts/check-reachability-dispositions.py`
  (50 groups disposition all 171: 149 CONNECT, 20 LIBRARY, 2 RETIRE).
- `scripts/check-shipped-surface-truth.py` → exit 0.

Origin re-fetched this round: `origin/develop` is still `435dc193`
(already the merge base of HEAD, so there is no develop-sync conflict to
resolve) and its `quality/ratchet-authorizations.json` `reachability`
section (11 entries: events.*, interop*, strike_recovery, graph.*,
…) contains **0** admission authorization rows. `scripts/ratchet_provenance.py`
`load_authorizations` reads that file **from the merge base**, so a
candidate-side grant provably cannot authorize (the gate's own docstring:
"a new grant does not take effect in the change that introduces it").
No open PR carries the grant either: PR #1945 (this branch) touches only
the banking ledgers, #1855 touches `durable-table-retention.json` /
`vulture-baseline.json`, #2109 touches no quality files. The two-merge
resolution is therefore unchanged and external to this lane: land the
reachability authorization for the two admission modules on develop
first, then merge develop into `auto-1893`. Adding it candidate-side
would be a no-op at best and violates issue #1893's explicit
"no baseline/grant/gate modifications to make an unwired slice green".

## Verdict

Every in-branch acceptance criterion of #1893 is independently re-proven
at this head, and both dispatched failures are resolved by evidence:
`test:` is green in CI and in every leg re-run here, and the
CI-repair-round ledger allowance was exercised (vulture CI-exact) and
found empty. The sole red is exact-debt-ledger's reachability
provenance, structurally unfixable in-lane by the two-merge rule while
`origin/develop` carries zero authorization rows and no open PR carries
the grant — external owner action (land the grant on develop), then
merge develop into this branch. This round makes no gate, ledger, grant
or production edits.
