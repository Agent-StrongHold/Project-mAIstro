---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair round

Frozen scope: issue #1893 only, starting head
`49b8bff0de80df9f6760e8d7b507394909aa0fa3`, supplied base
`66f3cea9e98980f146a12cf3142d66e30986d276`. Candidate edit files:
`packages/maistro-core/src/maistro/tasks/admission_codec.py`,
`packages/maistro-core/tests/tasks/test_admission_codec.py`, this note, and
`quality/vulture-baseline.json` only if the authorized exact scan requires it.
No activation, gate/grant changes, or new runtime consumer is authorized.

Initial evidence: clean worktree, expected HEAD. Supplied base and HEAD have
identical trees. Driver check-0 through check-4 report dependency sync, ruff,
format, focused tests (201 passed, 3 skipped), inventory passing. Prior result
reports the bound task_id repair already exists, real PostgreSQL tests passed
at an earlier head, and provenance remained blocked; none is proof for this head.
Assumption: repair assignment authorizes local work on the supplied branch, not
production activation or broader integration ownership. Current hosted `test`
failure has no failure trace supplied in the prompt; inspect captured evidence
before attributing it to codec behavior.

## Measured checkpoint

- Bound-row repair is already present at `admission_codec.py:290`: task_id is
  the binding receipt identity; tests independently assert the storage shape
  and cover unbound, bound, and acknowledged states. No duplicate repair.
- `uv sync --locked --extra dev`: exit 0.
- `RATCHET_BASE_REV=66f3cea9e98980f146a12cf3142d66e30986d276 uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: exit 0, 1326 reviewed identities = 1326 findings,
  no unbanked identities. No justified vulture ledger amendment.
- Same base environment with `uv run python scripts/check-ratchet-provenance.py`:
  exit 1, exactly the new reachability/disposition debt for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
  The gate resolves the trusted merge base to `34795962548a`, despite the
  supplied comparison tree being identical to HEAD. Banking is not approval.
- Docker is unavailable (`Cannot connect to the Docker daemon at
  unix:///var/run/docker.sock`); no PG variables supplied in this process.
  Do not count the driver's three skipped PG cases as durability evidence.
- Captured PR #1945 evidence names head `49b8bff0de80`, base `34795962548a`;
  historical inline findings cover missing legacy columns, scalar discriminator,
  whitespace identity, Unicode, nesting, numeric precision, and unwired debt.
  The codec now contains explicit checks for those data defects. No gate or
  authorization edits are within this repair scope except the conditional
  vulture exception above, which the exact scan did not require.

## Current-head validation (not inherited claims)

- `uv run ruff check .`: exit 0. `uv run ruff format --check .`: exit 0,
  3170 files formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: exit 0.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed, 3 skipped without PG configuration.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: exit 0; 15680 collected unique identities.
- `uv run python scripts/check-reachability.py`: exit 0; 1364 modules,
  171 unreachable. `check-reachability-dispositions.py`: exit 0; 50 groups,
  171 modules. `check-promotion-surface.py`: exit 0; 74 tolerated modules.
- Captured current-head `test` check is **success**, not failure:
  run `37820493418`, job `113459970683`. The only captured failed check at
  this head is `exact-debt-ledger`, run `37820493568`, job `113459969188`.
  The prompt's undated `test: failure` is therefore not current-head evidence;
  no speculative test repair is justified. No GitHub re-fetch or mutation.
- Native PostgreSQL 18.6 is available despite Docker being unavailable.
  Created a **new disposable DB** `maistro_1893_bdd7e66a` as local user `dev`.
  `DATABASE_URL=postgresql:///maistro_1893_bdd7e66a uv run alembic upgrade head`
  ran the real chain from empty through `060`, including `055` (exit 0).
- Re-ran both focused files with `MAISTRO_TEST_PG_DSN` and
  `MAISTRO_TEST_DATABASE_URL` both `postgresql:///maistro_1893_bdd7e66a`,
  `MAISTRO_REQUIRE_PG_LEGS=1`, and
  `-x -q -o junit_family=legacy --junitxml=/tmp/1893-bdd7e66a-pg.xml`:
  **204 passed, zero skips**. This proves the three migrated-table TEXT
  round-trips under independent raw/production-codec sessions and the corrupt
  Unicode boundary, not production activation or canonical Run admission.

Architectural reconciliation: reviewed accepted ADR-082826-b601 (one canonical
consumer; no inferred eligibility) and ADR-082826-d9f5 (RunStore alone owns
Run/NodeRun/Attempt identity). The codec remains a staged representation-only
leaf. Wiring an artificial caller to evade reachability, introducing an
execution authority, or treating synthetic fixture identities as authorized
admissions would violate these boundaries. No production source, schema,
tests, ledgers, or grants changed in this round.

## Regression and adjacent evidence

Using the same PG environment above, ran `uv run python -` with an in-process
wrapper around `encode_admission_record`: call the original then assign
`row['task_id'] = None`. `pytest.main` selected the existing bound unit
round-trip and bound raw/production-pool tests by full node ID. Both failed
as expected: independent `task_id == 'rcpt-1'` assertion at test line 134 and
PostgreSQL `ck_task_idempotency_v2_identity` at line 506. The probe asserted
`pytest.ExitCode.TESTS_FAILED`; no file was edited and no mutation persisted.
This is fresh failure evidence for the repaired regression, not reliance on
historical notes or encoder/decoder agreeing with each other.

Then, without the mutation, same PG environment and
`uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs
-x -q`: **2137 passed, 3 skipped, 5 warnings**, 2140 nodes, exit 0.
Warnings are aiosqlite worker-thread `Event loop is closed` in adjacent SQLite
store tests; they were not hidden or changed. Skips are not acceptance proof.

Focused JUnit evidence at `/tmp/1893-bdd7e66a-pg.xml` records separate backend
PIDs (production/raw) 105416/105418, 105419/105420, 105421/105422 for
unbound/bound/acknowledged respectively, all database
`maistro_1893_bdd7e66a` over local Unix sockets (address/port NULL). Each case
observed exactly one admission row and deletes its scope in `finally`.
After the broader adjacent suite the database is still revision `060`, with
3 admission rows / 3 distinct scope identities, 0 canonical Runs, 0 NodeRuns,
0 Attempts. These are suite-end counts, **not** proof of atomic Run admission;
this codec test deliberately inserts no canonical Run. DB retained for audit.

## Acceptance accounting and handoff

- Exact immutable DTOs/fresh flat mapping, strict storage UUID hex and signed
  timestamps: focused tests passed; bound regression mutation caught twice.
- Bound/unresolved/partial legacy evidence without invented identity; unknown
  formats fail closed; mismatched headers reject; scalar evidence survives
  snapshot/binding failures: focused tests passed.
- TEXT JSON duplicate/nonobject/nonfinite, nesting, Unicode and numeric-loss
  rejection; safe typed errors; tagged evidence/fingerprint preservation:
  focused tests passed. Existing tags remain untouched by the codec.
- Real migrated TEXT schema, raw versus production JSON codecs, all three v2
  binding states: executed, 204 focused tests with zero skips.
- No clock, request-fingerprint classification, SQL mutations, queue/HTTP
  changes or authority change: source inspection and unchanged source diff.
- Existing `request` storage column maps to DTO `request_snapshot`, per actual
  migration 055; do not rename the physical column from issue prose.
- Model materialization with `model_of`/`model_of_json`, Run JSONB insertion
  (object rather than string), authorized principals/Workspace/Project and
  registered Graph admission through a reachable consumer: **UNVERIFIED** by
  this representation-only suite; fixtures use literal evidence identities.
- Full required integration CI and production activation: **UNVERIFIED**;
  captured hosted test success is not a new full integration run.
- Exact-debt-ledger: **BLOCKED**, locally reproduced authorization failure for
  the two unwired modules. No vulture defect exists at this head. Resolution
  requires campaign-owner action on the trusted integration base or separately
  authorized consumer integration, not candidate-side grants or fake imports.

Only this note changed (inventory delta zero). `git diff --check` passed.
Progress: checked 1 assigned issue, done 0 complete repairs, skipped 0,
errors/blockers 1; next: owner resolves reachability authorization before
independent integration review. Do not redispatch another speculative codec
repair for the already-fixed bound-row bug or the captured green test job.
