# Issue #1893 bounded CI repair

## Current revalidation — job 000164664c544736be225d57ea51085a

**BLOCKED: reproduced trusted-base authorization failure; no demonstrated
source repair.** Frozen item: #1893, `auto-1893`, clean assigned source HEAD
`17d1aef40d08702666cf7e25f973b50b7abc2aae`, validated base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Only this existing report changes.
No incoming work, conflicts, source/test changes, ledger/grant/gate changes,
fetch/merge, production activation, or GitHub mutation. Inventory delta **0**;
no test addition requiring another inventory note.

Read repository instructions, supplied issue/failed-check evidence, prior result,
driver check-0 through check-4 logs, codec/DTOs and adjacent tests, exact-debt-ledger
workflow, and accepted ADRs 081226-a66b, 082826-b601, 082826-d9f5 and 083126-5e62.
Reconciliation: preserve Goal → Graph → Run → NodeRun → Attempt and canonical
store/consumer ownership; neither fake reachability imports nor activating the
later C consumer is authorized by this B2 repair. The Vulture exception does not
authorize reachability grants. Captured failed-check objects name different heads
(`3f2c79a70d9e` and `973772507c94`), with null summary/text; they do not establish
a failing node at this assigned head. Hosted `test: failure` remains UNRESOLVED.

### Fresh commands and evidence

Artifacts and executed JUnit node identities are under
`/home/dev/maistro/jobs/000164664c544736be225d57ea51085a/worker-*`.
Driver logs independently inspected: sync/lint/format pass, four focused files
346 passed / 3 PostgreSQL skips, inventory 16567. Fresh executions:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 reviewed identities / findings, zero unclassified. No ledger amendment justified. |
| `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized unreachable modules and two dispositions; `worker-provenance.log:17-30`. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -ra --junitxml=<job>/worker-focused.xml` | 346 passed, 3 PG skips, 3 JUnit-format warnings. Not durability proof. |
| `DATABASE_URL=postgresql:///maistro_1893_00016466 uv run alembic upgrade head` | PASS, fresh disposable DB, real chain from empty through 063. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -ra -o junit_family=legacy --junitxml=<job>/worker-pg.xml` | With DB environment below: **204 passed, zero skipped**. |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -ra` | Without PG environment: 1919 passed, 310 skipped, 6 aiosqlite event-loop-closed warnings. Skips are not PG evidence. |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS (3301 files). |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16567 unique nodes, zero duplicate evidence. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-reachability.py` / `uv run python scripts/check-reachability-dispositions.py` / `uv run python scripts/check-promotion-surface.py` | PASS against candidate evidence; does not authorize the failed provenance check. |

Native PostgreSQL **18.6**, user `dev`: confirmed `maistro_1893_00016466` absent,
then created it. `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` all targeted `postgresql:///maistro_1893_00016466`;
PG tests additionally used `MAISTRO_REQUIRE_PG_LEGS=1`, `REQUIRE_AUTH=false`,
`MAISTRO_DRY_RUN=1`. Non-null production-codec and independent raw pools used
session PID pairs **3177281/3177282**, **3177283/3177284**, **3177285/3177286**
for unbound/bound/acknowledged. Each persisted exactly one scoped row and read
identical named TEXT columns through both pools. Escaped-surrogate corruption
was injected into each snapshot column and safely rejected through both readers.
Final SQL PID **3177308**: revision **063**, **0 rows / 0 distinct generations /
0 distinct Run IDs** in `task_idempotency`. Database retained; no downgrade test.

Regression sensitivity: an in-memory encoder wrapper set `task_id=None` and ran
the existing bound round-trip test. It failed at `test_admission_codec.py:134`
as expected; harness required `TESTS_FAILED` and exited zero. No mutated source
was written (`worker-mutation.log`).

### Acceptance disposition

- Exact frozen/slotted header, typed codes/errors, strict UUID hex, signed
  timestamps, matching header, constructors and fresh flat mappings: inspected
  production definitions and corresponding focused tests passed.
- No guessed identity: bound/unbound/partial, receipt-only, pair-without-receipt,
  invalid evidence and ignored legacy `completed_at` tests passed. A pair lacking
  receipt evidence cannot satisfy the canonical binding without invention.
- Header/full-decode separation: expiry and fingerprint preserved despite full
  decode errors; unknown formats/scalar corruption fail closed. No clock,
  incoming fingerprint, assessment, SQL mutation, HTTP/queue or scope change.
- Snapshot fidelity/error hygiene: canonical-byte round trips, unchanged stored
  fingerprint, tags, strict JSON/duplicates/nonobjects/nonfinite rejection,
  numeric-loss/Unicode/deep-nesting and suppressed error-chain tests passed.
- Real migrated two-pool storage contrast: all three states passed, sessions and
  SQL counts above. Physical `request` TEXT maps to DTO `request_snapshot`.
- Production behavior: import search finds codec → identity and Vulture whitelist
  → identity only; **no production codec consumer**, consistent with
  `admission_codec.py:50-53`. Tests are storage/DTO evidence, not admission.
- **UNVERIFIED:** original-model evidence-json/model_of materialization and
  fingerprint-before-tagging pipeline, Run JSONB object insertion, authorized
  principal/Workspace/Project/registered-Graph admission through the codec,
  full required integration CI. Live replacement/409 ordering belongs to C/F2.
- **BLOCKER:** candidate entries at `quality/reachability-baseline.json:131,147`
  and `quality/reachability-dispositions.json:612-613` cannot authorize themselves;
  exact-debt-ledger fails against the assigned trusted base. An already-passing
  Vulture ledger must not be changed to disguise this different failure.

Next: owner-coordinated trusted-base authorization/integration resolution, plus
the actual hosted failing step/head/traceback. Do not redispatch the same
source/base expecting a different authorization result. This local commit is a
blocked handoff, not integration approval.
Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner prerequisite
and concrete hosted failure evidence}`.

## Current revalidation — job 5696cb77cba142a786ea3b4c1c13f095

**BLOCKED: the trusted-base reachability prerequisite still fails.** Frozen
scope: issue #1893 only, assigned `auto-1893` worktree, clean source HEAD
`b71153e1a80a40ef56c765d8642590e53c97d4dd`; supplied and validated base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. This existing report is the only
repository edit. No source/test/ledger/grant/gate changes, activation, fetch,
merge, or GitHub mutation. No incoming edits or sync conflict existed. No test
addition: inventory delta **0**, no new inventory note required.

Read repository instructions, frozen issue contract, driver `check-0.log`
through `check-4.log`, prior result, codec/DTO constructors and adjacent tests,
and exact-debt-ledger workflow. Accepted ADRs 081226-a66b, 082826-b601,
082826-d9f5 and 083126-5e62 preserve Goal → Graph → Run → NodeRun → Attempt,
sole canonical execution/store ownership, and trusted-base authorization.
Reconciliation: neither adding a fake runtime import nor activating the later
consumer is an authorized repair of this inactive B2 leaf. The explicit
Vulture exception does not permit reachability policy changes.

### Executed evidence at the source HEAD above

Logs and executed node identities (JUnit) are under
`/home/dev/maistro/jobs/5696cb77cba142a786ea3b4c1c13f095/worker-*`.
Driver logs independently inspected: sync/lint/format/inventory pass;
346 passed / 3 skipped. Those skips are not database proof.

| Command | Fresh result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 reviewed identities, 1322 findings, zero unclassified. No ledger amendment justified. |
| `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py` | **FAIL, exit 1**: two unauthorized modules and two dispositions; other subchecks pass. |
| `uv run alembic upgrade head` | PASS: newly created disposable PostgreSQL 18.6 DB, real chain from empty through 063. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused.xml` | **204 passed, zero skipped**, including all three two-pool PostgreSQL states. |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -ra` | 1919 passed, 310 skipped, 6 warnings; separate invocation without PostgreSQL environment. Not proof of the skipped legs. |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16567 unique nodes, no duplicate evidence. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-reachability.py` / `uv run python scripts/check-reachability-dispositions.py` / `uv run python scripts/check-promotion-surface.py` | PASS against candidate evidence; does not authorize the provenance failure. |

Database `maistro_1893_5696cb77` was confirmed absent before `createdb` and is
retained. `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL`
all targeted `postgresql:///maistro_1893_5696cb77`; focused tests also set
`MAISTRO_REQUIRE_PG_LEGS=1`, `REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`.
Non-null production-codec pool and independent raw pool session PIDs were
**2895335/2895336**, **2895337/2895338**, **2895339/2895340** for unbound,
bound, acknowledged respectively, on the same Unix-socket database. Each
persisted exactly one scoped row, read named TEXT columns, compared exact DTOs,
injected escaped-surrogate corruption into all three snapshot columns, checked
safe typed errors through both pools, and deleted its row. Final SQL at PID
**2895391**: revision **063**, **0 rows / 0 generations / 0 Run IDs** in
`task_idempotency`. No downgrade/migration test suite was run in this round.

Regression sensitivity: an in-memory wrapper forced encoder `task_id=None`
and executed the existing bound round-trip node through `pytest.main`.
The assertion at `test_admission_codec.py:134` failed as expected; the harness
required `TESTS_FAILED` and exited zero. No mutated source was written. The
broader suite's six warnings concern aiosqlite worker callbacks after event-loop
closure, retained as residual lifecycle warnings rather than silently omitted.

### Acceptance and remaining decision

- **Exact interfaces and immutable records:** inspected header/DTO definitions,
  six typed error codes, named columns, strict UUID hex, signed timestamps,
  header agreement and fresh flat mapping; corresponding focused tests pass.
  Physical `request` TEXT maps to DTO `request_snapshot` per the real schema.
- **No invented identity:** bound/unbound/partial legacy, receipt-only,
  task-without-Run, invalid evidence and ignored `completed_at` tests pass.
  A pair without receipt evidence stays partial because the canonical binding
  requires receipt identity; the decoder cannot fabricate it.
- **Header separation:** expiry/fingerprint survive full decode errors;
  unsupported formats and invalid scalar headers fail closed. No clock,
  incoming fingerprint, assessment or claim decision was introduced.
- **Snapshot fidelity/error hygiene:** canonical bytes, unchanged fingerprint,
  evidence tags, strict JSON, duplicate/nonobject/nonfinite rejection,
  Unicode/numeric-loss/deep-nesting and suppressed parsing-chain tests pass.
- **Real database contrast:** all three raw/production pool states pass against
  the migrated schema with identities/counts above, not fake or skipped PG.
- **Production boundary:** import search finds codec → identity and Vulture
  whitelist → identity only. `admission_codec.py:50-53` correctly states that
  there is no production consumer. SQL mutation, HTTP/queue behavior, scope
  utility and canonical execution authority are unchanged.
- **UNVERIFIED:** original-model evidence-json/model_of materialization,
  fingerprint-before-tagging pipeline, Run JSONB object INSERT and authorized
  principal/Workspace/Project/registered-Graph admission through this codec.
  Synthetic storage DTOs do not prove those paths. Live replacement/409 ordering
  belongs to C/F2, not B2; full integration CI also remains UNVERIFIED.
- **Actual blocker:** `worker-provenance.log:17-30` rejects
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` against
  the supplied trusted base. Candidate entries at
  `quality/reachability-baseline.json:131,147` and
  `quality/reachability-dispositions.json:612-613` cannot authorize themselves.
- **Hosted `test: failure`:** no failing node or traceback is supplied and no
  failure was reproduced in scoped validation. Attribution remains UNRESOLVED;
  do not apply guessed source fixes or rebank an already-passing Vulture ledger.

Next: owner-coordinated trusted-base authorization/integration resolution and
the actual hosted failing step/head/traceback. No repeat dispatch on unchanged
source/base can cure that authorization prerequisite. Local report commit is a
blocked handoff, not merge or activation approval.
Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner prerequisite
and concrete hosted failure evidence}`.

## Previous revalidation — job f506636f76f948c1983452e2a533ac70

**BLOCKED; no reproduced source/test defect or unbanked Vulture identity.**
Frozen assignment: issue #1893 only, branch `auto-1893`, clean starting HEAD
`c99fcdaf9d079e01dcbd6f7732201aeedcae5281`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62` (resolved before use). The provenance
checker resolves their trusted merge base to
`2154f845347c9541016288c760f8da3f5cd2e064`. No conflict, incoming edits, fetch,
merge, activation, GitHub mutation, or quality-ledger/grant/gate change occurred.
This existing report is the only changed file. No tests changed; inventory delta
is **0**, so no new inventory note is required. Historical sections are retained,
not relied upon as current proof.

Read repository instructions, frozen issue/PR evidence, driver check-0 through
check-4 logs, prior result, codec and adjacent tests, and the CI gate invocation.
Accepted ADRs 081226-a66b, 082826-b601, 082826-d9f5 and 083126-5e62 preserve the
canonical Goal → Graph → Run → NodeRun → Attempt spine, sole execution/store
ownership, and trusted-base authorization. Reconciliation: an inactive typed
codec does not authorize activating the C consumer to satisfy reachability.
The Vulture-ledger exception does not authorize reachability policy edits.
The assigned writer lane establishes this bounded worktree scope, not rollout
or independent merge approval. Captured linked PR heads differ from this HEAD;
their claims are not current execution evidence.

### Fresh executed validation

All commands ran at the source SHA above with long timeouts. Logs, the bounded
DB validation harness, captured evidence, and 204 executed node identities are
under `/home/dev/maistro/jobs/f506636f76f948c1983452e2a533ac70/worker-*`
(and `validate-pg.py`). Driver checks were independently inspected: sync, lint,
format, inventory pass; 324 passed / 3 PG skips is not durability proof.

| Command | Observed result |
| --- | --- |
| `uv sync --locked --extra dev` | PASS, 256 resolved / 214 checked. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 reviewed identities / 1322 findings; zero unclassified. No ledger amendment justified. |
| `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py` | **FAIL, exit 1**: two unauthorized unreachable modules and two dispositions; all other subchecks pass. |
| `uv run pytest tests/migrations/test_migration_chain.py -x -q` | 18 passed, using a freshly created disposable PostgreSQL database before runtime tests. |
| `uv run alembic upgrade head` | PASS; final real-chain revision 063. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused.xml` | **204 passed, zero skipped**. |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -ra` | **2226 passed, 3 skipped, 100 warnings**, 2229 collected. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16543 unique nodes. |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger; not authorization. |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger; not authorization. |
| `uv run python scripts/check-promotion-surface.py` | PASS. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `git diff --check` | PASS before report update; repeated before commit. |

The DB harness created **maistro_1893_f506636f** only after confirming it absent,
on the existing `maistro-postgres` container, PostgreSQL **18.6**. Both
`MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` target that same disposable
DB; `DATABASE_URL` targets it for Alembic, and `MAISTRO_REQUIRE_PG_LEGS=1` prevents
silent codec skips. Credentials are not recorded here. `REQUIRE_AUTH=false` and
`MAISTRO_DRY_RUN=1` match the test environment, not production activation.

The three codec states use non-null production-codec `pg_pool` and an independent
raw asyncpg pool. Recorded production/raw PIDs: unbound **267802/267803**, bound
**267804/267805**, acknowledged **267806/267807**; server identity
`172.20.0.2/32:5432`, database `maistro_1893_f506636f`. Each state persists exactly
one scoped row through migration-055 constraints, compares named TEXT columns
and exact DTOs, injects escaped-surrogate corruption into each snapshot column,
requires typed errors through both readers, and deletes its row. Final SQL after
the *broader adjacent suite* (PID **269125**) reports revision **063**, **3 rows /
0 distinct non-null generations / 2 distinct Run IDs** in `task_idempotency`.
Do not report zero residue for that broader run. The isolated DB is retained.

The adjacent skips concern archive/retention capabilities, not missing PostgreSQL.
Its 100 warnings include SQLAlchemy non-checked-in connection cleanup and
unawaited asyncpg cancellation coroutines; these are residual test-lifecycle
warnings, not silently counted as clean output or repaired outside this leaf.

Regression sensitivity was executed, not assumed: an in-memory encoder wrapper
forced `task_id=None`, then ran the existing bound round-trip case via
`pytest.main`. It failed at `test_admission_codec.py:134` (`None != 'rcpt-1'`),
and the harness verified `TESTS_FAILED`. No mutated source was written to disk.
This independently tests storage shape rather than encode/decode agreement.

### Acceptance accounting and disposition

- **Typed interfaces/immutable DTOs:** inspected frozen/slotted header, six error
  codes, header agreement, signed timestamps, strict UUID hex, constructors and
  fresh flat mapping; corresponding focused tests pass. Physical `request` TEXT
  maps to DTO `request_snapshot`, matching the migrated schema rather than adding
  an alternate column or mutation authority.
- **No inferred identity:** bound/unbound/partial legacy, receipt-only,
  task-without-Run, unreadable evidence, and ignored `completed_at` cases pass.
  A legacy pair without receipt evidence stays partial because the canonical
  binding requires a receipt; no identity is fabricated to satisfy it.
- **Header/full-decode separation:** named expiry/fingerprint preservation,
  mismatched header, scalar corruption and unknown-format cases pass. The codec
  accepts neither clock nor incoming fingerprint. Live replacement/409 ordering
  belongs to C/F2 and is **UNVERIFIED**, not a claim of these unit tests.
- **Snapshots/error hygiene:** canonical byte round trips, strict JSON object /
  duplicate / bare-nonfinite rejection, unchanged stored fingerprint, tagged
  evidence retention, deep nesting, lossy-number and Unicode cases pass. Error
  messages suppress parsing chains and do not disclose injected evidence.
- **Real storage contrast:** all three raw/production pool states execute on the
  migrated database with session identities and persisted row counts above;
  no fake or skipped PostgreSQL case is used as proof.
- **Original-model pipeline:** evidence-json/model_of/model_of_json
  materialization, fingerprint-before-tagging, Run JSONB object INSERT, and
  authorized principal/Workspace/Project/registered-Graph admission remain
  **UNVERIFIED for this leaf**. Synthetic DTO/storage fixtures and adjacent
  admission tests do not prove a production codec consumer.
- **Production boundary:** source search finds only codec → identity and Vulture
  whitelist → identity imports; no production codec caller. The inactive
  boundary remains explicit at `admission_codec.py:50-53`. No scheduler, store,
  authorization, SQL mutation, queue/HTTP, scope utility, or assessment changed.
- **Required gates:** the exact provenance failure persists at
  `quality/reachability-baseline.json:131,147` and
  `quality/reachability-dispositions.json:606-613`: both admission modules are
  new/unapproved relative to trusted base. Candidate-ledger passes cannot
  authorize them; the Vulture-only exception cannot repair this failure.
- **Hosted `test: failure` / full integration CI:** **UNVERIFIED and unattributed**.
  No failing node was reproduced in driver or fresh scoped checks. The hosted
  job also contains other packages/frontends/root tests; these subsets are not
  a full-job pass. No speculative or cosmetic test repair was made.

**Next:** an authorized owner must resolve the coordinated trusted-base
reachability prerequisite or provide an approved real integration path, then
assign synchronization/revalidation. Supply the actual failing hosted test step,
head and traceback before another test-repair dispatch. This worker cannot land
that grant, activate the consumer, or mutate GitHub. Progress:
`{checked: 1, done: 0, skipped: 0, errors: 1, next: owner resolution and failing-test evidence}`.
This locally committed handoff is not merge approval; the repair remains blocked.

## Previous revalidation — job 5e8721073a6a498eaaa797e238052e81

**BLOCKED.** Issue #1893 only; assigned worktree `/home/dev/Git/wt/auto-1893`,
branch `auto-1893`, clean starting source
`1cdc1e01453d556ab2f57f708c14ba60d22b9f2b`. Supplied base and resolved local
`origin/develop`: `2154f845347c9541016288c760f8da3f5cd2e064`. No merge conflict
or incoming uncommitted work. No remote refresh, GitHub mutation, activation,
or ledger/grant/gate change. This existing handoff is the only changed file;
no tests were added, so inventory delta is **0**. Earlier evidence is preserved,
not assumed true. The requested repair remains unfinished, not merge-approved.

Read repository instructions, frozen dispatch issue body, supplied prior result
and check-0 through check-4 logs, codec/identity constructors and adjacent tests,
and the exact-debt-ledger workflow. Accepted ADRs 081426-1f7c, 082526-7f02,
082826-b601 and 082826-d9f5 preserve Attempt-owned execution mechanics,
immutable admission provenance, and the canonical consumer/store. Reconciliation:
a staged DTO codec is not authority to activate a consumer to satisfy a gate.
The explicit exception permits reviewed Vulture identity changes only, not
reachability authorization. A guessed ADR filename was not found; the actual
081426-1f7c execution-runtime-contract file was resolved and read instead.

### Fresh validation

All commands ran in the assigned worktree with long timeouts at the source SHA
above. Logs and collected node IDs: `/home/dev/maistro/jobs/5e8721073a6a498eaaa797e238052e81/worker-*`.
Driver logs separately report passing sync/lint/format, 324 passed / 3 skipped,
and inventory 16543; skipped cases are not used as durability evidence.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1322 reviewed
  identities / 1322 findings, zero unclassified. No ledger amendment is justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**, unchanged required gate.
  `worker-provenance.log:20-29` rejects both new unreachable modules and their
  dispositions: `maistro.runs.admission_identity`, `maistro.tasks.admission_codec`.
  Trusted base has 169, candidate 171. Candidate entries remain at
  `quality/reachability-baseline.json:131,147` and
  `quality/reachability-dispositions.json:612-613`. This is not Vulture debt.
- Confirmed fresh DB name absent; `createdb maistro_1893_5e872107`, then
  `DATABASE_URL=postgresql:///maistro_1893_5e872107 uv run alembic upgrade head`:
  **PASS**, real migration chain from empty through **063**, PostgreSQL **18.6**.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_5e872107`, plus `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/worker-focused.xml`:
  **204 passed, zero skipped**. Separate `--collect-only -q` saved 204 node IDs.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q` without PG environment:
  **1919 passed, 310 skipped, 6 warnings** (aiosqlite callbacks after loop closure).
  This broader result does not establish skipped PostgreSQL behavior.
- `uv run ruff check .`: **PASS**; `uv run ruff format --check .`: **PASS**, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  **PASS**, 16543 nodes. `uv run python scripts/check-shipped-surface-truth.py`: **PASS**.

The three real two-pool tests require non-null production `pg_pool`, assert
matching database/server identity and distinct sessions, and insert one scoped
row each through the real migration-055 constraint. Production/raw backend PIDs
from JUnit: unbound **799129/799131**, bound **799132/799133**, acknowledged
**799134/799136**, all on `maistro_1893_5e872107` over Unix socket. They compare
named TEXT columns and DTOs, inject escaped-surrogate corruption into each
snapshot column, require typed errors through both pools, and delete their rows.
Final direct SQL: revision **063**, **0 rows / 0 generations / 0 Run IDs** in
`task_idempotency`. Database retained for inspection. No new mutation/pre-fix
failure is claimed: this round changed no source or tests.

### Acceptance and remaining blockers

| Criterion | Executed evidence / limit |
| --- | --- |
| Exact frozen DTO/header interfaces, named columns, fresh flat encoding, strict UUID hex and signed timestamps | Focused 204-case suite and inspected constructors/codec; header mismatches and paired v2 binding columns asserted independently. |
| Bound/unbound/partial legacy evidence, no invented identity, unsupported formats fail closed | Named legacy and unknown-format tests plus receipt-only, missing-receipt, whitespace and partial-pair cases pass. |
| Header expiry/fingerprint survives failed full decoding; no assessment/clock | Named header separation tests pass; decoder accepts neither a clock nor incoming fingerprint. Live expiry/409 precedence is a later consumer concern, not proven here. |
| Canonical snapshot bytes, unchanged fingerprint, strict JSON and safe errors | Named round-trip/nonfinite/invalid JSON tests pass, plus lossy-number, deep-nesting and Unicode rejection. Canonical fixtures do not prove original-model serialization. |
| Raw and production pool TEXT equivalence on real migrated schema | All three states passed against PostgreSQL 18.6, with actual sessions and row counts above; no skipped/fake DB counted. |
| No competing execution authority or production activation | Production import search finds codec -> identity and Vulture whitelist -> identity only. Codec has no production caller; no SQL mutation, HTTP/queue or live assessment change made. |
| Actual evidence-json/model_of materialization, fingerprint-before-tagging, Run JSONB object INSERT, authorized principals/Workspace/Project/registered Graph | **UNVERIFIED**. Synthetic DTO/storage fixtures are not authorized production admission. |
| Unchanged full required integration CI | **UNVERIFIED**; trusted-base provenance fails. Generic hosted `test: failure` remains **UNATTRIBUTED**; supplied deterministic logs and fresh scoped tests have no failing node. |

All ten prospective test names execute, but this is codec/storage evidence,
not reachable production acceptance. Owner-coordinated trusted-base resolution
or separately approved real integration is required; candidate-side banking,
fake imports, or the Vulture-only exception cannot resolve the proven blocker.
Request the actual hosted failing step/traceback before assigning another test
repair. Do not rerun this unchanged source/base expecting authorization to change.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: coordinated
reachability prerequisite and concrete hosted test failure evidence}`.

## Previous revalidation — job 5e5bd0612b8c423b81f41ca949bbf5fa

**BLOCKED; no reproduced defect permits a source or ledger repair.** Frozen
scope: issue #1893 only, assigned `auto-1893` worktree; clean starting HEAD
`99e44481e61864cb30fa0109486ded289b0fb361`. Supplied base and resolved local
`origin/develop` both equal `2154f845347c9541016288c760f8da3f5cd2e064`.
No conflict, missing ref, or uncommitted work required salvage or a merge.
This section is the only change; preceding work is preserved below.

Read repository instructions, the captured issue body and linked #1325/#1855
PR evidence, driver check-0 through check-4 logs, prior result, codec and
adjacent tests. Accepted ADR-081226-a66b, ADR-081626-f383 and ADR-082226-5104
retain canonical execution, execution-fence ownership and PostgreSQL durable
authority. The codec remains mapping/DTO conversion, not admission authority.
No activation, competing scheduler/store, SQL mutation, HTTP/queue mapping,
clock, incoming fingerprint, live assessment or scope-policy change is made.
Legacy pairs without receipt evidence remain typed partial failures: the
canonical binding needs receipt identity, which the codec must not invent.

### Fresh validation at the starting HEAD

Logs: `/home/dev/maistro/jobs/5e5bd0612b8c423b81f41ca949bbf5fa/worker-*.log`.
All commands used the assigned worktree and long tool timeouts.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  **324 passed, 3 skipped**, 327 cases. PostgreSQL contrasts skip at
  `test_admission_codec.py:470` because both test DSNs are unset.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1322 reviewed
  identities, zero unclassified. No Vulture ledger amendment is warranted.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python
  scripts/check-ratchet-provenance.py`: **FAIL, exit 1**. Two new unreachable
  modules and two dispositions lack trusted-base authorization:
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
  Evidence is `quality/reachability-baseline.json:131,147` and
  `quality/reachability-dispositions.json:612-613`. This is the unchanged
  required gate in `.github/workflows/vulture-ratchet.yml:77`.
- Production-source import search confirms only codec -> identity and Vulture
  whitelist -> identity references; no production codec consumer. Its own
  source states the inactive boundary at `admission_codec.py:50-53`.
- Driver logs independently record passing sync, lint/format, the same
  focused tests and suite inventory (16543 nodes, no duplicate evidence).
  These are inspected driver evidence, not additional worker executions.

### Acceptance and handoff

The acceptance audit retained below was checked against current source and
fresh tests. Pure contract criteria pass: exact shared interfaces and frozen
DTOs; named fields/header agreement; signed timestamps/strict UUID hex; six
safe typed failures; legacy bound/unbound/partial distinctions; header evidence
surviving corrupt snapshots/bindings; unknown-format rejection; strict TEXT
JSON and unchanged stored fingerprint; fresh flat mapping and v2 paired IDs.
Tests inject malformed storage evidence, not mocked admission outcomes.

**UNVERIFIED this round:** live migrated PostgreSQL/raw versus production
pools, session identities and final row counts; original-model fingerprint /
evidence-json / model_of materialization; Run JSONB object INSERT; authorized
principal/Workspace/Project/Graph integration; consumer expiry/409 precedence;
and unchanged full integration CI. Canonical fixture tags do not prove the
model pipeline. Skips or historical live runs do not prove current durability.
No tests were changed or added, so inventory delta is zero and no new
mutation/pre-fix result is claimed.

The generic remote `test: failure` remains **UNATTRIBUTED**: supplied logs and
fresh focused tests contain no failing node. CI's `test` job has broader
package/frontend/root steps; focused passes are not a full-job pass.
The confirmed blocker is reachability provenance, not Vulture. Its repair
needs separately coordinated trusted-base authorization or approved real
consumer integration; neither is authorized by this leaf or the Vulture-only
exception. No gate/grant/ledger edits, fake imports, GitHub mutation or
integration approval occurred. Preserve the implementation and request the
exact failing CI step/traceback before another speculative repair round.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: coordinated
reachability prerequisite and current failing CI traceback}`. Local commit
records this bounded handoff only; issue #1893 is not merge-ready.

## Previous revalidation — job 1bb1dda4c99c4edf908183ced7a62f3a

**BLOCKED; no evidence-backed code or Vulture ledger repair is available.**
Starting source: `3c4e0cc86ec3701b1b9e6c92b508cbfef859643e`, clean assigned
worktree `/home/dev/Git/wt/auto-1893`. Both the supplied develop base and the
resolved local `origin/develop` are
`2154f845347c9541016288c760f8da3f5cd2e064`. No sync conflict was present.
No remote state was refreshed, and no merge or activation was performed.

Frozen item: issue #1893, using this job's supplied `dispatch-context.json`,
check-0 through check-4 logs and previous result artifact. Inspected the codec,
identity constructors, adjacent codec/identity/CLI tests, existing inventory
note, repository instructions and exact-debt-ledger workflow. This report is
the only changed file; no tests were added, so the inventory delta is zero.
The previous sections below are retained as historical evidence, not assumed
verification.

### Fresh commands and outcomes

All commands used `uv run` from the assigned worktree. Logs are saved as
`repair-*.log` in `/home/dev/maistro/jobs/1bb1dda4c99c4edf908183ced7a62f3a/`.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py
  packages/maistro-core/tests/extensions/test_cli_lock.py -x -q -rs`:
  **324 passed, 3 skipped**; 327 collected cases. All three skips are the
  raw/production PostgreSQL pool contrasts: both DSNs are unset.
- `uv run pytest packages/maistro-core/tests/extensions -x -q`:
  **1068 passed**. The already-repaired CLI wrapping test passes at all three
  terminal widths. This does not identify the unnamed remote `test: failure`.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3301 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **PASS**, 16543 collected nodes, no duplicate
  evidence. Existing inventory notes require no change.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1322 reviewed
  identities, zero unclassified. No missing/stale identity justifies the
  permitted Vulture ledger amendment.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python
  scripts/check-ratchet-provenance.py`: **FAIL (exit 1)**. Both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add
  unreachable modules and dispositions without trusted-base authorization
  (169 trusted modules versus 171 candidate modules). The failure is in
  reachability provenance, not Vulture.
- `rg -n 'admission_codec|admission_identity' packages/*/src --glob '*.py'`:
  only the codec's identity import and the Vulture whitelist's identity
  import; **no production codec consumer**. This agrees with the provenance
  gate and the modules' explicit inactive-contract documentation.

### Acceptance review and reconciliation

The acceptance table below was rechecked against the current codec source,
constructors and freshly executed tests. Pure contract evidence passes for
all nine non-PG prospective test names: immutable DTO round trips and fresh
flat mappings; storage-only UUID hex; distinct bound/unbound/partial legacy
evidence; header/full-decode separation preserving expiry and fingerprint;
unknown-format refusal; tagged nonfinite preservation without fingerprint
recomputation; invalid/duplicate JSON refusal. Additional executed tests
cover signed timestamp bounds, header mismatch, safe typed errors, lossy
numbers, excessive nesting, Unicode corruption and v2 binding constraints.
The byte-preservation tests start with canonical snapshots: they do not prove
preservation of arbitrary noncanonical source bytes or an end-to-end model
serialization pipeline.

**UNVERIFIED this round:** live migrated PostgreSQL durability, raw/production
pool equivalence, database session identities and residue counts, actual
`model_of`/`model_of_json` materialization, canonical Run JSONB object storage,
authorized principals/Workspace/Project/registered Graph integration, consumer
expiry/409 precedence, and unchanged full integration CI. No mocked return,
skipped case, historical PG result or candidate-ledger pass is counted as
proof. No new regression/mutation result is claimed because no code/test
change was made.

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`, immutable admission provenance,
and protected-base authorization. The issue forbids activating a consumer or
modifying reachability policy to make an inactive slice green. The explicit
CI-repair exception allows reviewed Vulture identity bookkeeping only; it
cannot authorize the failing reachability additions. Thus the previous block
cannot safely be resolved in this lane by a dummy import, local grant or
ledger edit. No SQL mutation, queue/HTTP mapping, assessment, clock,
scope-utility, admission policy or authorization change was introduced.

### Handoff

Owner-coordinated trusted-base reachability resolution (or a separately
approved real consumer) is required before this candidate can pass the
unchanged exact-debt-ledger gate. A resolved base already containing the
necessary authorization is not available in the frozen local snapshot.
The original remote `test: failure` remains **UNATTRIBUTED**; supplied driver
checks and focused fresh test runs pass. Do not repeat speculative code or
ledger repairs without new evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner-coordinated
reachability resolution and live integration evidence}`. Commit this report
locally as the bounded handoff; it is not integration approval.

## Previous repair — frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `38b6c44e617dfd70d9f344da9d4236fe48b7f6a2` (verified); base: `2154f845347c9541016288c760f8da3f5cd2e064` (verified).
- Single item: issue #1893 CI repair. Input is the supplied `af14316a265b47059b168a5bf8bde783/dispatch-context.json`, not refreshed GitHub state.
- Inspection: admission codec/identity and adjacent tests, CLI lock failure named by the prior result, relevant ADRs and exact CI gates.
- Potential changes frozen to this report, `packages/maistro-core/tests/extensions/test_cli_lock.py`, its inventory note, and the explicitly permitted Vulture ledger only if the exact scan demonstrates a discrepancy. No reachability ledger/grant or production activation changes.

## Initial evidence and assumption

Worktree initially clean. Supplied check-0 through check-4 logs report dependency sync, lint, formatting, 312 passing / 3 skipped focused tests, and suite inventory passing. These are driver evidence, not fresh validation by this worker.

The prior job result reports a reproducible wrapped diagnostic assertion at `test_cli_lock.py:138`, alongside a trusted-base reachability blocker. Assumption: reproduce and repair the actual CI test failure if present; leave unauthorized reachability additions unchanged and report the blocker. The issue prohibits production activation and baseline/grant changes to disguise an unwired codec. No conflict or develop-sync evidence requires a merge.

## Reproduced evidence

- `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py -x -q`: **1 failed, 6 passed**, line 138. Rich wraps after `not`, so the contiguous phrase assertion fails although the invalid lock is rejected with exit code 1 and the correct diagnostic. This is actual local evidence for the requested CI test repair, not proof of the unnamed remote failure's identity.
- Exact requested Vulture scan: **PASS**, 1322 findings, zero unclassified; no ledger amendment justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: **FAIL**, admission_identity and admission_codec both lack trusted-base authorization for their new unreachable-module and disposition rows. No permitted local bookkeeping change resolves this.
- Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-083126-5e62. Preserve canonical execution and immutable admission provenance; the protected base remains authorization authority. No activation or gate changes are proposed.

## Repair and validation

Changed `packages/maistro-core/tests/extensions/test_cli_lock.py`: normalize rendered whitespace while retaining the exit-1 and complete diagnostic assertions, including the rejected and supported lock formats. Parameterize the existing real CLI invocation at 40, 80, and 120 columns. Production rendering and lock rejection remain unchanged. Inventory delta is +2 in `docs/testing/inventory-notes/issue-1893-cli-wrap-repair.md`.

Commands executed against the starting HEAD plus this repair:

- Pre-fix regression check, with new width parameters but the old assertion: `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py -q -k invalid_lock`: **2 failed (40/80 columns), 1 passed (120 columns)**. Injected boundary is terminal rendering width, not parser/CLI return mocking.
- `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`: **324 passed, 3 skipped** (DSNs absent).
- `uv run pytest packages/maistro-core/tests/extensions -x -q`: **1068 passed**.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, **16543** nodes, no duplicate evidence.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger (1403 production modules, 171 unreachable).
- `uv run python scripts/check-reachability-dispositions.py`: PASS against candidate ledger (50 groups).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `rg -n 'admission_codec|admission_identity' packages/*/src --glob '*.py'`: only codec -> identity and Vulture whitelist -> identity imports; no production codec consumer.
- `git diff --check`: PASS.

Vulture and trusted-base provenance results are recorded above. No Vulture amendment is needed: the scan found no missing or stale identity. Candidate-ledger passes do not override the provenance failure.

## Acceptance audit

Inspected the codec, identity constructors, codec tests and production CLI loader. The existing detailed audit in `issue-1893-repair-validation.md` is historical; the following states only this round's evidence.

| Criterion | Current evidence / limit |
| --- | --- |
| Exact shared APIs, frozen/slotted header, immutable DTOs, fresh flat mapping | Source inspection and freshly executed codec/identity tests pass. |
| Named columns, strict storage UUID hex, signed timestamps, supplied header must match row | Focused header mismatch, scalar range, schema/version, UUID and binding tests pass. Live SQL persistence UNVERIFIED. |
| Six typed failure codes, validated scope only, safe messages and suppressed parsing chain | Focused invalid header/snapshot/record and partial legacy tests pass, including deep nesting, numeric precision and surrogate corruption. |
| Legacy bound/unbound/partial/receipt-only, no identity guessing | Focused tests pass. A task/run pair without receipt evidence remains partial because the canonical binding constructor requires a receipt; inventing it would violate the no-guessing contract. completed_at supplies no authority. |
| Header/full decode separation, expiry/fingerprint evidence survives corruption, unknown formats fail closed | Named prospective pure tests pass; no clock or incoming fingerprint enters the codec. Replacement/409 precedence belongs to the future consumer and is UNVERIFIED. |
| Strict TEXT snapshots, duplicate/nonobject/bare nonfinite refusal, tag and fingerprint preservation | Focused tests pass. Fixtures supply tagged snapshots/fingerprints; actual model -> fingerprint -> evidence-json -> model_of/model_of_json materialization is UNVERIFIED. |
| Raw/production pools on same disposable migrated PostgreSQL DB | UNVERIFIED: three PG cases skipped for missing DSNs. No migration, DB session identity, final row-count or durability evidence claimed this round. |
| Run JSONB is an object, explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED: pure codec fixtures are not authorized admission or canonical Run insert evidence. |
| No SQL mutation, HTTP mapping, queue/live assessment/scope/activation/policy change | No production changes this round; source remains a pure mapping/DTO codec. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt is preserved. |
| Focused tests, lint/format, applicable mypy and inventory | PASS as recorded, with PG skips explicitly excluded from proof. CLI regression is demonstrated before and after repair, extensions suite fully passes. |
| Reachable production consumer and unchanged full required integration CI | BLOCKED: no consumer; trusted-base provenance rejects the existing two unreachable-module/disposition additions. Full integration CI and attribution of the remote `test: failure` are UNVERIFIED. No gate/grant/ledger change to conceal this. |

## Handoff

Changed files: CLI lock test, +2 inventory note, and this report. No GitHub mutations, activation, merges or destructive git operations. No conflict was present. The CLI repair is ready for handoff, but issue #1893 remains **BLOCKED** by trusted-base reachability authorization and the unverified integration acceptance above. Resolution requires owner-coordinated authorization on the trusted base or an authorized real consumer, not repeated candidate-ledger edits.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: coordinated reachability resolution and live integration evidence}`. This round must be committed locally; it does not grant integration approval.

## Repair at 973772507c94 — supplied pack collision failure

Frozen scope: issue #1893, job `88e144df073146a3b862fef1d0b06457`, starting
HEAD `973772507c94428dba24fad7d9530490688d59e2`, assigned base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Worktree started clean. Read the
captured issue body, supplied check-0 through check-4 logs and prior result;
no GitHub state was refreshed or mutated. Unlike the earlier unattributed
failure, this job's `check-3.log` identifies a concrete regression at
`test_pack_contracts.py:876`, reproduced locally before editing.

The production registry rejects an active-extension identity collision with
`PackIdentityConflict`, but the branch-added test expects stale diagnostic
wording. Match the actual diagnostic and extend the same test with a real
post-refusal dependent install requiring the original extension version. The
mutation experiment confirms that the extension-version corruption this test
names is detected. No production implementation or test collection changes.
See `docs/testing/inventory-notes/issue-1893-pack-collision-repair.md` for exact
commands, counts, pre-fix and mutation failures and the zero inventory delta.

Fresh results: focused suite **346 passed / 3 PG skips**; extensions suite
**1092 passed**; lint, format, scoped source mypy, exact Vulture, inventory,
candidate reachability/dispositions, shipped-surface and promotion gates pass.
The unchanged trusted-base provenance gate **fails**: both admission modules
are new unreachable identities with unauthorized dispositions. Production
import search finds only codec -> identity and Vulture whitelist -> identity,
not a codec consumer. No Vulture ledger change is warranted (1322 reviewed
identities match); no reachability grant/ledger/gate edit is permitted here.

### Acceptance checked this round

| Criterion | Executed evidence / remaining limit |
| --- | --- |
| Frozen/slotted header, exact shared APIs and immutable DTOs; fresh flat encode mapping | Source inspection plus codec/identity tests in the focused run pass. |
| Named SQL columns, UUID .hex, signed timestamps, header/row equality | Focused schema, UUID, range and mismatch tests pass; live SQL UNVERIFIED. |
| Six typed failure codes, validated scope only, safe messages/suppressed parse chains | Focused corrupt-header/snapshot/record and legacy-partial tests pass, including deep nesting, precision loss and surrogate cases. |
| No inferred legacy work identity; bound/unbound/partial and receipt-only remain distinct | Focused legacy tests pass. A pair lacking receipt evidence remains partial because the #1851 binding constructor requires receipt identity; no identity is invented. completed_at conveys no authority. |
| Scalar header survives malformed snapshot/partial binding; unknown format fails closed | Named prospective pure tests pass. No clock or incoming fingerprint enters the codec; replacement/409 precedence belongs to C/F2, not this leaf, and is UNVERIFIED. |
| Strict TEXT JSON, no duplicate keys/nonobject/bare nonfinite tokens; tags and fingerprint preserved | Pure tests pass. Actual model -> original fingerprint -> evidence-json -> model_of/model_of_json materialization is UNVERIFIED; fixtures supply tags rather than exercise that production path. |
| Raw and production pools against the same disposable migrated DB | UNVERIFIED: three PG tests skipped for unset DSNs; no migration, session identities, final SQL counts or durability proof claimed. |
| Run JSONB is an object; explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED: codec fixtures and the pack test are not authorized admission or canonical Run INSERT evidence. |
| No SQL mutation, HTTP/queue/live assessment/scope/policy/activation changes | No production changes this round. Mapping-only codec remains inactive. |
| Focused tests, lint/format, applicable mypy, inventory and integration gates | Focused checks pass as recorded; provenance FAILS; full required integration CI UNVERIFIED. |
| Reachable production behavior / independent mergeability | BLOCKED: no runtime codec consumer and no trusted-base authorization. Test imports and candidate baselines do not establish reachability. |

ADR reconciliation: accepted ADR-081226-a66b preserves the single canonical
Goal -> Graph -> Run -> NodeRun -> Attempt model; this repair adds no execution
authority. Accepted ADR-083126-5e62 requires protected-base quality authority;
passing candidate-ledger scans cannot authorize the two admission modules.
Production activation is explicitly outside the issue's stage authorization.
No merge conflict was present and the supplied develop base is already merged;
a speculative sync cannot repair the reproduced assertion or authorize debt.

Changed files this round: the existing pack collision test, its zero-delta
inventory note and this report. Final disposition: **BLOCKED**, with the named
CI test regression repaired. Owner-coordinated trusted-base authorization or a
separately authorized real consumer remains necessary; do not manufacture
reachability or self-authorize a grant. Local commit is a handoff only.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner-coordinated
provenance resolution and live integration evidence}`.
