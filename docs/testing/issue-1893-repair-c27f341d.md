# Issue #1893 repair — c27f341d

## Assignment and fresh blocker evidence

Only issue #1893 in `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
Clean starting HEAD: `751984ef56895ed922f00d481b157c1b10305ac3`.
Frozen develop base and resolved local `origin/develop`:
`ac7370141e8e61bd6f352bca35ed0b505104aadb`.
No uncommitted incoming work; all existing branch work preserved.

Read repository instructions, documentation authority map, issue body from frozen
`dispatch-context.json`, prior result and driver `check-0.log`–`check-4.log`.
Driver reports sync/lint/format/inventory pass and 346 passed, 3 skipped;
these are not independent live PostgreSQL evidence.

Read accepted ADR-081226-a66b, ADR-081426-1f7c and ADR-082526-aef8.
Reconciliation: preserve Goal → Graph → Run → NodeRun → Attempt, and B2's
no-activation/no-assessment constraint. Test imports and public exports are not
production reachability; adding an artificial consumer would not be a repair.
The generic hosted `test: failure` contains no failing node or traceback.
Assumption: reproduce focused tests and exact gates rather than speculate.

Fresh commands (logs under `/home/dev/maistro/jobs/c27f341d72084d1d97eaed08df6b97c4/`):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **exit 0**, 1322 reviewed identities / 1322 findings (`worker-vulture.log`). No unbanked identity; no Vulture ledger amendment warranted.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: **exit 1** (`worker-provenance.log`). Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules and new dispositions without trusted-base authorization. Other component checks pass.

This is a reproduced authorization blocker, not a merge conflict. The Vulture-only
exception does not permit editing reachability ledgers or grants. No gate,
authorization, ledger, production activation, SQL mutation or HTTP policy changes
will be made to conceal it.

## Focused validation checkpoint

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: **346 passed, 3 skipped**, 349 collected; PostgreSQL variables unset (`worker-focused.log`).
- `uv run ruff check .`: pass; `uv run ruff format --check .`: pass, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: pass, 2 source files.
- Production import search finds only codec → identity and the Vulture whitelist import. No reachable runtime consumer; consistent with source staging notice at `admission_codec.py:50–53`.
- One exploratory search named nonexistent `migrations/env.py` (not found; skipped). Actual Alembic configuration identifies `alembic/env.py`, which was read instead. No command was run against a guessed migration ref.
- Docker inspection found the existing `maistro-postgres` pgvector/pg18 service on localhost port 5433. Plan: create a uniquely named disposable DB for this job, migrate it, run mandatory non-skipped pool contrasts, and remove only that DB. Shared application DBs will not be tested or truncated.

## Real PostgreSQL acceptance checkpoint

Created only job-owned disposable database `issue_1893_c27f341d` on the existing
pgvector PostgreSQL 18.6 server. Passed matching nonempty `DATABASE_URL`,
`MAISTRO_TEST_DATABASE_URL`, and `MAISTRO_TEST_PG_DSN` privately to subprocesses;
no credentials written to the report. Set `MAISTRO_REQUIRE_PG_LEGS=1`.

- `uv run alembic upgrade head`: exit 0, real chain from empty DB through 001–063, including 055 (`worker-pg-migration.log`). No downgrade test run or claimed.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs -o junit_family=legacy --junitxml=<job>/worker-pg.xml`: **204 passed, zero skips** (`worker-pg-focused.log`).
- Raw and production pools matched DB/server identity (`issue_1893_c27f341d`, `172.20.0.2/32`, port 5432) with distinct backend PID pairs: unbound 361927/361928; bound 361929/361930; acknowledged 361931/361932. Each observed exactly one persisted admission row. JUnit properties record all identities/counts.
- Existing tests inject escaped-surrogate corruption into each of the three TEXT snapshots through SQL, check both pools reject it safely, restore original text, then delete the test row. Unbound/bound/acknowledged INSERTs satisfy the real migration constraints.
- Final SQL: Alembic revision 063; `task_idempotency` count 0; `canonical_runs` count 0 (`worker-pg-state.log`). Dropped only `issue_1893_c27f341d` afterward.
- These are storage codec tests, not authorized positive admissions. Fixture principals are literal strings and no Run was created. Do not infer authorization, Run JSONB materialization or atomic admission from them.
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0 (`worker-shipped.log`).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: exit 0 (`worker-inventory.log`).
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -rs`: **1919 passed, 310 skipped, 5 warnings**, 2229 collected, without database variables (`worker-adjacent.log`). Skips are not durability evidence; warnings are aiosqlite worker threads encountering closed event loops.
- `uv run python scripts/check-reachability.py`: exit 0, 1403 production modules / 171 unreachable (`worker-reachability.log`).
- `uv run python scripts/check-reachability-dispositions.py`: exit 0, 50 groups / 171 modules (`worker-dispositions.log`). These candidate-ledger consistency passes do **not** override the failed trusted-base authorization checks.
- Inline `uv run python` assertions: `AdmissionRowHeader` has no `__dict__`, mutation raises `FrozenInstanceError`, and decoder signatures contain only row/header (no clock or incoming fingerprint): pass.
- Core suite inventory: 16567 unique nodes, no duplicate evidence. `git diff --check`: pass.

## Acceptance matrix at the starting source SHA

| Criterion | Executed evidence / limitation |
| --- | --- |
| Required frozen/slotted header and public interfaces | Source inspection plus inline immutability/signature assertions; focused type checking passes. |
| Strict scalar header, supported format/schema, matching header/row | Existing mismatch, unknown-format, missing-column and signed timestamp tests pass in the 204-test suite. |
| Exact immutable v2/legacy records; no inferred identity | Existing bound/unbound/partial, receipt-only, missing-receipt, whitespace and corrupt-binding tests pass. |
| Header evidence survives snapshot/binding failure | Named expiry/fingerprint preservation tests pass. No clock, decision, claim or live assessor change. |
| Fresh flat named-column mapping; UUID `.hex` only at storage; binding receipt agreement | Existing unit tests and three real PostgreSQL INSERT/read contrasts pass, including bound/acknowledged migration-055 constraint shapes. |
| Typed errors, validated scope, no unsafe snapshot/token diagnostics | Negative tests pass for malformed/duplicate/nonobject/nonfinite JSON, bad identities, extreme nesting, lossy numbers and escaped surrogates; suppression and safe messages asserted. |
| Snapshot bytes, permitted tagged evidence and unchanged fingerprint | Canonical round-trip and tagged nonfinite-token tests pass, including real TEXT pool parity. These fixtures encode tag objects directly: production `model_of`/`model_of_json` materialization and actual original-model fingerprint generation are **UNVERIFIED**. |
| Raw/production pools against same real migrated DB | 204 passed / zero skips with mandatory PG legs, schema 063, distinct same-server session PIDs and one persisted row per state; final admission/Run counts both zero. |
| Run payload is a JSONB object, not doubly encoded text | **UNVERIFIED**: B2 creates no Run; no actual Run JSONB INSERT asserted by these tests. |
| Explicit authorized principals, Workspace/Project, registered Graph for positive admissions | **UNVERIFIED**: storage DTO fixtures are not admissions; no runtime consumer exists. No activation permitted in this leaf. |
| Focused tests/lint/format/mypy/inventory and existing test notes | Pass as detailed above; no test additions or inventory-count change in this round. Existing inventory note read; no new inventory delta needed. |
| Unchanged full integration CI and reachability authorization | **NOT SATISFIED**: trusted-base provenance fails for both modules/dispositions. Full hosted CI remains **UNVERIFIED**; generic `test: failure` not reproduced by scoped suites and no hosted traceback supplied. |
| Canonical ownership, stage constraints and scope | No production/test/gate/ledger changes in this round. B2 remains inactive; no new authority, SQL mutation path, HTTP response, queue policy or closure action. |

## Handoff

**BLOCKED**, not merge-ready. Fresh failure evidence:
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606–613` add two modules without
trusted-base authorization. CI's exact-debt-ledger invokes the failing gate at
`.github/workflows/vulture-ratchet.yml:77`. This failure cannot be resolved by
the permitted Vulture-only ledger exception; Vulture itself has no unbanked debt.

Owner/coordinator must resolve the staged integration under the existing
two-merge authorization policy before this candidate can rely on any grant.
No new branch sync was attempted: the frozen local develop ref already resolves
to the supplied base and the failure is not a sync conflict. Obtain the actual
hosted failing test node/traceback before changing code for `test: failure`.
Production model materialization, Run JSONB insertion, authorized admission and
full hosted CI remain outside this round's proven evidence.

Only changed file: `docs/testing/issue-1893-repair-c27f341d.md` (this report).
No speculative implementation repair identified, so no code/test changes and no
new mutation/pre-fix failure claimed. All incoming branch work preserved; no
push, GitHub mutation, closure or integration action. Report committed locally.

Progress: checked 1, done 0 (implementation repair), skipped 1 (blocked), errors 1
(provenance); next: authorized staging resolution plus hosted failing-test evidence.
