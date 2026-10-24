---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 CI-repair round at 367c4568d8fb (job 8b032636)

Snapshot: issue #1893 only; branch `auto-1893`, starting HEAD verified exactly
`367c4568d8fb9367f42578208a38943b878fcb9b`, worktree clean, develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7` re-fetched and re-confirmed as
`origin/develop` (no upstream movement; merge-base equals the develop tip, so
no develop sync was needed). No GitHub mutations, no source or test edits, no
ledger/grant edits this round (docs only).

The prior round's job (e15bc9d2) died on a provider timeout after its checks
had already passed; every claim below is independently re-executed evidence
from THIS round, not carried over.

## Fresh evidence executed this round (all commands run at this head)

- `uv run ruff check .` -> PASS; `uv run ruff format --check .` -> PASS
  (3277 files already formatted).
- `uv sync --locked --extra dev --extra bootstrap` (CI `test` job env) then
  `uv run mypy --strict packages/maistro-core/src` -> PASS (784 files,
  exit 0; zero errors now that `maistro_bootstrap` extras are installed —
  the 5 `import-not-found` notes from the previous round were an
  extras-environment artifact, files untouched by this branch).
- Vulture, CI-exact argv (vulture-ratchet.yml:77): `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` -> PASS (1323 reviewed identities -> 1323
  findings, exit 0). No unbanked vulture debt exists; the CI-repair-round
  permission to amend `quality/vulture-baseline.json` has nothing to act on.
- Candidate gates: `check-reachability.py` PASS (1396 modules, 171
  unreachable); `check-reachability-dispositions.py` PASS (50 groups: 149
  CONNECT, 20 LIBRARY, 2 RETIRE); `check-shipped-surface-truth.py` PASS;
  `check-promotion-surface.py` PASS; `check-suite-inventory.py --suite
  packages/maistro-core/tests` PASS (16466 node IDs, delta 0).
- Focused pytest, no PG: `test_root_admission_identity.py` +
  `test_admission_codec.py` -> 201 passed, 3 skipped (the PG legs).
- Durable PG leg, independently reproduced on a NEW disposable database
  created for this round (`maistro_1893_v8b0326`, name confirmed absent
  before CREATE) on the pgvector/pg18 PostgreSQL 18.6 instance at
  127.0.0.1:5433: `uv run alembic upgrade head` migrated the real chain
  001->062 (exit 0); reran the two focused files with
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both targeting that
  database and `MAISTRO_REQUIRE_PG_LEGS=1` -> **204 passed, 0 skipped,
  exit 0**. Post-run SQL residue: `task_idempotency` 0 rows,
  `canonical_runs` 0 rows, `alembic_version` = 062. (Operator error note:
  the first attempt failed 3 tests because this shell expands `export`
  arguments before assigning, so `MAISTRO_TEST_PG_DSN="$MAISTRO_TEST_DATABASE_URL"`
  captured empty; rerun with separate exports — a shell-usage bug, not code.)
- CI `test` job selection, CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`,
  after `uv sync --locked --extra dev --extra bootstrap`):
  `uv run pytest tests/ --ignore=tests/tools/registry -q` -> **4971 passed,
  129 skipped, exit 0** (4m48s); `uv run pytest
  packages/maistro-server/tests packages/maistro-turing/tests
  packages/maistro-turing/backend/tests packages/maistro-design/tests
  packages/maistro-ext-harness/tests packages/maistro-ext-sdk/tests -q` ->
  **1849 passed, 9 skipped, exit 0** (1m02s).
- Trusted-base provenance, CI-shaped: `RATCHET_BASE_REV=origin/develop uv
  run python scripts/check-ratchet-provenance.py` -> FAIL (exit 1),
  reproduced exactly: `check-reachability-provenance.py` flags
  `maistro.runs.admission_identity` + `maistro.tasks.admission_codec` as
  NEW unreachable modules absent from the trusted base, and
  `check-reachability-dispositions-provenance.py` flags their two NEW
  dispositions as absent from the trusted ledger (169 -> 171). No other
  ratchet in the battery fails.

## Dispatch snapshot check-run triage (the named `test: failure`)

The snapshot's per-check-run data confirms the prior round's triage: the only
failing `test` check-run is at head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`
started 2026-10-03 — the head of PR #1855 (issue #1572's lane). At this
branch's PR #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355`
(2026-10-11), `test` is SUCCESS and the only failing check is
`exact-debt-ledger`. Both halves of the `test` job pass at this head under
CI's environment (counts above). No repair target for `test` exists on this
branch; the #1855 failure belongs to that lane.

## The one red gate remains structurally blocked on the two-merge rule

`check-ratchet-provenance.py` resolves the trusted base as the merge-base
with `origin/develop` = `3c761d14`, which contains no reachability
authorization for the two modules. In-branch alternatives are all prohibited:
wiring the modules would violate B2's "typed representation only" scope;
editing the gate or self-authorizing violates the issue's "no baseline/grant/
gate modifications to make an unwired slice green". The vulture half of the
same CI job is green via the `_vulture_whitelist.py` scanner-input mechanism
(diff vs develop adds only the #1851/#1845 reference lines: the
`AdmissionAssessment` import, three named module variables, six whitelist
entries). Resolution stays upstream: land the reachability authorization for
`maistro.runs.admission_identity` + `maistro.tasks.admission_codec` on
develop (two-merge rule), then merge develop into `auto-1893`.

## Repaired-line liveness (new this round, in-memory mutation proof)

- `admission_identity.py` `AdmissionRecordV2.__post_init__` (the
  `binding.receipt_id != envelope.receipt_id` guard): a directly constructed
  mismatched binding raises `ValueError`; monkeypatching `__post_init__`
  with the guard removed lets the same construction succeed — the line is
  the enforcement, not decoration.
- `admission_codec.py::encode_admission_record` emits `task_id` and
  `run_id` together from the binding (`rcpt-1`/`run-1` when bound, both
  NULL when unbound), matching migration 055's
  `ck_task_idempotency_v2_identity` CHECK
  (`(task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND
  run_id IS NOT NULL AND task_id = receipt_id)`), which the round-trip test
  asserts independently of encode/decode agreement.

## Scope hygiene re-verified

`git diff origin/develop...HEAD` production surface is exactly:
`packages/maistro-core/src/maistro/tasks/admission_codec.py` (new),
`packages/maistro-core/src/maistro/runs/admission_identity.py` (new, #1851
prerequisite), `packages/maistro-core/src/_vulture_whitelist.py` (+#1851
reference lines), the two test files, `quality/reachability-baseline.json`
(+2 rows), `quality/reachability-dispositions.json` (+1 group), and docs.
`alembic/` is untouched on this branch (migration 055/062 chain arrives from
develop per #1892 B1). No SQL mutation, HTTP mapping, or queue change exists
in the diff; the only production-adjacent importer of either new module is
`_vulture_whitelist.py` (scanner input, ships in no wheel). No
fixes/closes/resolves keyword against #1893 in any commit
(`git log origin/develop..HEAD` grep: 0 matches); commit subjects reference
`(#1893)` only; PR #1945 body says "Refs #1893" per the dispatch snapshot.

Verdict of this round: all B2 functional acceptance criteria hold at this
head under fresh independent execution, including the real-PostgreSQL
durability leg; the remaining red is the upstream two-merge sequencing only.
