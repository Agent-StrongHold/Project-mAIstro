# Issue #1893 repair checkpoint

## Current bounded recheck — job 758cab57

**BLOCKED; no source repair justified.** Starting HEAD was verified as
`1b1b9037f379bee9fbbb9329b2bbd2b33bd00b44`, with a clean worktree. The supplied
base and local `origin/develop` both resolve to
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. No sync conflict exists.
Only #1893 in the assigned `auto-1893` worktree was processed; the supplied
issue/PR snapshot was not refreshed. This section records new execution,
not adoption of earlier verification claims.

Read repository instructions, accepted ADR-081226-69ee and ADR-081426-1f7c,
the complete codec/identity modules and their tests, the quality-gate policy,
and the exact-debt-ledger workflow. Reconciliation: retain the staged,
representation-only scope and canonical Goal -> Graph -> Run -> NodeRun ->
Attempt authority. An artificial consumer or candidate-approved reachability
grant is not an authorized repair.

All five supplied `check-*.log` files pass (driver tests: 346 passed, three
skipped). They provide no failing node for the reported `test: failure`.
That ambiguity remains **UNRESOLVED**, not grounds for speculative changes.
Fresh logs are in `/home/dev/maistro/jobs/758cab5734dd458e9eead8670ce904af/`:
`worker-vulture.log`, `worker-provenance.log`, `worker-pytest.log`, and
`worker-quality.log`. Commands ran with 1,200-second tool timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **pass**, 1,322 reviewed findings, zero unclassified. No Vulture amendment warranted.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: **exit 1**. Both admission modules are new unauthorized unreachable modules and have new unauthorized dispositions: four violations, 169 trusted versus 171 candidate entries. Other provenance subgates pass.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`: **2,064 passed, 310 skipped**, 2,374 nodes, 49.44s. Six adjacent aiosqlite thread-cleanup warnings report closed event loops; no failed assertion. Skips are not durability evidence.
- `uv run ruff check .`: pass; `uv run ruff format --check .`: pass (3,301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: pass, two files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass, 16,567 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: pass.
- `uv run python scripts/check-reachability.py`: pass against candidate baseline, 1,403 modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: pass candidate shape, 50 groups / 171 dispositions.
- `uv run python scripts/check-promotion-surface.py`: pass, 74 tolerated modules. Candidate-ledger checks do not override failed trusted-base provenance.

### Acceptance and limits at this source SHA

| Criterion | Fresh evidence / limit |
| --- | --- |
| Shared interfaces, frozen/slotted header, immutable DTOs, fresh flat SQL mapping | Complete source inspection and executed contract tests pass. |
| Named columns, strict UUID hex, signed timestamps, header/row agreement | Executed scalar/schema/UUID/mismatch tests pass; physical `request` maps to DTO `request_snapshot`. |
| Six typed errors, validated scope, no raw snapshot/token in messages or displayed parsing chains | Executed safe-error tests pass, including excessive nesting, numeric loss and invalid Unicode injections. |
| Legacy bound/unbound/partial and receipt-only; no guessed identity or completed_at authority | Executed legacy tests pass. Bound pairs without receipt evidence remain partial because canonical binding requires receipt identity. |
| Header expiry/fingerprint survives full-decode failure; unknown format fails closed | Named prospective tests pass. Inclusive expiry/409 consumer precedence is outside B2 and UNVERIFIED here. |
| Strict JSON TEXT; duplicate/nonobject/bare nonfinite rejection; snapshot/tag/fingerprint preservation | Executed JSON tests and unbound/bound/acknowledged round trips pass. Fixed fingerprints and handcrafted tags do not prove original-model fingerprinting or materialization. |
| Evidence-json serialization and model_of/model_of_json materialization of arbitrary context | UNVERIFIED end-to-end: no production codec consumer was found. |
| Real migrated DB, matching nonempty DSNs, both pools, binding CHECK, Run JSONB object and final SQL/session counts | UNVERIFIED this round: PostgreSQL cases skipped; no database execution claimed. Historical PG evidence is not fresh proof. |
| Authorized principals/Workspace/Project and registered Graph kinds | UNVERIFIED through admission: codec fixtures use synthetic identities. |
| No clock, claim mutation, SQL mutation, HTTP/queue/assessment/scope/policy changes | Complete codec inspection confirms mapping-only behavior; no production/test code changed. Production import search finds only codec -> identity and the whitelist import. |
| Inventory and required integration gates | Scoped checks above pass; full integration CI UNVERIFIED and trusted-base provenance BLOCKED. |

Only this existing handoff was updated. No tests were added or changed, so
inventory delta is zero and no new inventory note is needed. No new mutation
or pre-fix failure is claimed. The Vulture-only ledger exception cannot resolve
the actual reachability blocker. No ledger, grant, gate, activation, remote,
or destructive Git changes were made.

Next: owner coordination must establish the trusted-base prerequisite, and the
actual failing CI SHA/step/node/traceback is needed for a targeted test repair.
Do not redispatch identical inputs as if another passing scoped run fixes this.
Progress: `{checked: 1, done: 0 repairs, skipped: 0 issues, errors: 1 failing gate,
next: trusted-base prerequisite and failing-test evidence}`. Local commit is a
preserved handoff, not integration approval.

## Previous bounded recheck — job 237b1bfe

Frozen scope: issue #1893 only, assigned worktree `/home/dev/Git/wt/auto-1893`,
starting HEAD `c18d070b9ab9a45ee4e36e9d253517fc9a017e42`, supplied develop
base `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Clean starting worktree.
Candidate changes are restricted to the existing codec/identity files, their
adjacent tests and inventory notes if an actual defect is reproduced, and this
handoff. Vulture ledger changes require actual unbanked retained identities;
no other grant, ledger or gate edits are permitted.

Read the frozen issue body and supplied check-0..4 logs: dependency sync, lint,
format and inventory pass; focused tests report 324 passed, three skipped.
The prior result is BLOCKED, not a successful repair. Ambiguity: the named
`test: failure` supplies no current-head traceback; assume no source defect
until reproduced. Existing historical evidence below is not fresh validation.
No remote refresh or expanded issue list is authorized or needed.

Fresh gate results: exact Vulture command passes (1,322 findings, 1,322 reviewed
identities, zero unclassified); no ledger amendment is warranted. Provenance
with the supplied base exits 1: trusted merge base `2154f845347c` contains 169
reachable-disposition exclusions versus 171 candidate exclusions. Both
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` have new
unauthorized dispositions and unreachable-module entries. Logs are
`worker-vulture.log` and `worker-provenance.log` in this job directory.

Read accepted ADR-081226-a66b, ADR-082826-b601 and ADR-083126-5e62. Reconciliation:
keep canonical execution authority and staged representation-only scope;
candidate bookkeeping cannot authorize itself. This is a policy prerequisite,
not a merge conflict or Vulture debt. No speculative source repair is justified.

### Fresh focused validation and acceptance

All commands below ran at the starting source SHA, with a 1,800-second timeout:

- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 3,301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: pass.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  **324 passed, three skipped**, 327 nodes; `worker-focused.log` in the job
  directory. The skipped nodes explicitly require both PostgreSQL DSNs.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: pass, 16,543 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: pass.
- `git diff --check`: pass before final documentation update.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: pass as recorded above.
- `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python
  scripts/check-ratchet-provenance.py`: **FAIL**, exit 1 as recorded above;
  this is the required workflow step at `.github/workflows/vulture-ratchet.yml:77`.

| Acceptance criterion | Fresh evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces, fresh flat encoding, named columns and matching scalars | Codec/DTO inspection plus executed immutable, scalar-mismatch, fresh-mapping and round-trip cases pass. |
| UUID `.hex` only at storage, signed timestamp validation, six typed safe failure codes | Executed UUID/scalar/schema/corruption tests pass, including suppressed parser chains and validated scope hashes. |
| Legacy bound/unbound/partial distinctions without invented identity | Executed tests pass, including receipt-only, one-sided binding, bound pair without receipt and unreadable original data. Canonical DTO requires a receipt, so absent receipt remains explicit partial evidence. |
| Header/full-decode separation; unknown format fail-closed | Executed expiry/fingerprint preservation and unknown-format tests pass. Consumer inclusive expiry/409 ordering is outside B2 and UNVERIFIED here. |
| Strict JSON TEXT, canonical snapshot bytes, tag and stored-fingerprint preservation | Executed duplicate/nonobject/nonfinite/numeric-loss/Unicode tests and all three v2 state round trips pass. |
| Original-model fingerprinting, existing evidence-json serialization, `model_of`/`model_of_json`, arbitrary context materialization | UNVERIFIED: tests handcraft tags and use a fixed fingerprint; passing round trips do not establish materialization. |
| Real migrated PostgreSQL, raw/production pools, paired binding CHECK, Run JSONB object insertion, sessions and final SQL counts | UNVERIFIED this round: all three PostgreSQL cases skipped; no database was created or queried. Historical database results below are not adopted as fresh evidence. |
| Explicit authorized principals/Workspace/Project and registered Graph kinds | UNVERIFIED: codec fixtures use synthetic strings and no authorized admission path. |
| No clock, claim, SQL mutation, HTTP/queue/assessment/scope/legacy-policy change | Full codec inspection confirms staged mapping-only behavior. No production files changed. |
| Runtime reachability and unchanged required integration CI | UNVERIFIED/blocked: source import search finds only codec -> identity and whitelist import; provenance rejects both new unreachable modules. No full integration CI claim. |
| Inventory, scoped typing and formatting | Commands above pass. No tests added or changed; inventory delta zero, so no new inventory note. |

**BLOCKED; no source repair claimed.** Only this handoff changed. There is no
new pre-fix or mutation failure to report. The unspecified hosted `test: failure`
remains UNRESOLVED: supplied deterministic logs and this focused run contain no
failing node. Do not modify source or Vulture bookkeeping speculatively.

Next action: obtain the exact failing test SHA/step/node/traceback and resolve
trusted-base staging authorization with the integration owner. An already-landed
reachability authorization or separately authorized real consumer is required;
this lane cannot create one. No fetch/merge was attempted because no sync
conflict exists and no new authorized base was supplied. No push, GitHub
mutation, grant/gate change, activation or destructive operation occurred.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base
coordination and current-head failing-test evidence}`. Commit this handoff;
do not redispatch unchanged inputs as though passing focused tests repaired CI.

## Previous bounded recheck — job 22566a54

This section records newly executed evidence, not adoption of the historical
claims below. Source SHA: `532da33e2594afb646023ef870611f1ea157dbcd`;
frozen develop ref: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Assigned branch/worktree were clean and matched dispatch. Only #1893 was
processed; no remote lists were refreshed. The only repository change this
round is this handoff. No tests were added or changed; inventory delta is zero.

**BLOCKED, not repaired.** The exact Vulture command passes with 1,322 findings
and 1,322 reviewed identities; no ledger amendment is justified.
`RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python
scripts/check-ratchet-provenance.py` exits 1. Its resolved trusted merge base is
`2154f845347c9541016288c760f8da3f5cd2e064`. Both admission modules are new
unauthorized unreachable modules and new unauthorized dispositions (169 trusted
versus 171 candidate). The Vulture-only exception cannot authorize reachability
policy changes. This is not a worktree conflict; merging without an already
landed authorization does not resolve it.

Read repository instructions, the full codec and its tests, prerequisite DTO
constructors, existing inventory, CI provenance workflow, and accepted
ADR-081226-a66b, ADR-082826-b601, and ADR-083126-5e62. Their reconciliation stays:
retain the canonical execution spine and inactive representation-only scope;
never add fake reachability or candidate-controlled grants to pass a gate.
Production-source import inspection finds only codec -> identity and the
Vulture whitelist, not a runtime admission consumer.

### Commands and actual outcomes

Logs are retained in
`/home/dev/maistro/jobs/22566a5457d34191b8434c8534ba64a5/worker-*.log`;
PostgreSQL JUnit evidence is `worker-pg.xml` in that directory.

- Supplied `check-0.log` through `check-4.log` were read: all passing, with
  three skipped PostgreSQL cases. They contain no failing test traceback.
  Captured check metadata names a failed `test` at a different head
  (`3f2c79a70d9e...`), with no output text, and an `exact-debt-ledger` failure
  at `90d4c278e6d7...`. Neither identifies a current-head failing test.
- `uv run ruff check .` and `uv run ruff format --check .`: pass.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: pass.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: pass.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: pass, 16,543 collected nodes.
- `uv run python scripts/check-shipped-surface-truth.py`: pass.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  **324 passed, 3 skipped**, 327 nodes; PG skips are not durability evidence.
- Verified disposable `maistro_1893_22566a54` did not exist, then created it.
  `DATABASE_URL=postgresql:///maistro_1893_22566a54 uv run alembic upgrade head`:
  pass, real empty-to-063 chain on PostgreSQL 18.6, including migration 055.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_22566a54`, and `MAISTRO_REQUIRE_PG_LEGS=1`, ran
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job-directory>/worker-pg.xml`:
  **204 passed, zero skipped**. Production/raw backend PIDs were
  2117835/2117836 (unbound), 2117837/2117838 (bound), and 2117845/2117849
  (acknowledged), all on that database via local socket. Each case persisted
  one scoped row and exercised both readers, including corrupt TEXT injection.
  Independent final SQL session 2117880 confirmed revision 063 and zero
  admission rows, generation identities, bound Run identities, canonical Runs,
  NodeRuns, and Attempts. Database retained for inspection; no downgrade run.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **1,919 passed, 310 skipped,
  6 warnings** (2,229 nodes). This broader run had no PG DSNs. Warnings concern
  existing aiosqlite worker threads encountering closed event loops; no fix
  or production-impact conclusion is claimed.

### Current acceptance limits and next action

Executed focused cases prove strict UUID/scalar/schema validation, frozen DTOs,
fresh paired binding mappings, legacy bound/unbound/partial distinctions,
header/full-decode separation, strict JSON TEXT, safe typed failures, canonical
snapshot/tag/fingerprint preservation, and real raw/production pool equivalence.
The existing tests use synthetic identities, handcrafted tags and a fixed
fingerprint: they do **not** establish original-model fingerprinting,
`model_of`/`model_of_json` materialization, authorized Workspace/Project/Graph
admission, or Run JSONB object insertion through a reachable production caller.
Those criteria and full integration CI remain **UNVERIFIED**. Consumer expiry/
409 ordering is deliberately not B2 behavior. No new regression test or mutation
claim is made because this round found no actionable codec defect.

The reported `test: failure` remains **UNRESOLVED**. Obtain its exact failing
SHA/step/node/traceback and resolve trusted-base staging authorization through
the integration owner before another repair dispatch. Do not interpret passing
scoped tests as repair of an unidentified CI failure. No push, GitHub mutation,
source activation, gate modification, grant edit, or destructive Git operation.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base
coordination and current-head failing-test evidence}`. This documentation commit
is a preserved handoff, not integration approval.

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `6bc5e32be8d8430a869dbb64115653c9dae21bb2`; supplied develop base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Only issue #1893; no GitHub mutations or re-enumeration. Starting worktree clean.
- Inspect existing admission codec/identity implementation, adjacent tests, inventory note, relevant ADRs, supplied dispatch and check logs. Candidate edits restricted to evidence-backed codec/test repairs, corresponding inventory notes, and this handoff. The vulture ledger may be amended only for observed retained identities as explicitly authorized; other ledgers/grants/gates are out of scope.
- Ambiguity: dispatch says `test: failure` without a failing node. Reproduce named gates and focused tests before considering any code change. Existing coordination/activation blocks are not authorization to wire this staged codec into production.

## Progress

- Verified exact starting HEAD and clean status. Read issue body from frozen dispatch snapshot; stage is pure immutable codec, not live admission activation.
- Supplied check-0..4 logs: dependency sync, ruff, format and inventory pass; focused driver tests 324 passed / 3 skipped. No failing test node supplied. Read prior result/report as historical evidence only.
- Executed exact Vulture command: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings / reviewed identities, zero unclassified. No ledger amendment justified.
- Executed `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), unauthorized new unreachable modules and dispositions for `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` (169 trusted -> 171 candidate). Other wrapper subgates pass. Local origin/develop resolves to the supplied base; no sync conflict exists.
- This reproduces the required exact-debt-ledger blocker. The Vulture-only exception does not permit reachability authorization edits. Full integration readiness is BLOCKED.
- Executed `uv run ruff check .` and `uv run ruff format --check .`: PASS (3301 formatted files); scoped `uv run mypy` on admission codec/identity: PASS (2 files).
- Executed `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: 324 passed, 3 PostgreSQL skips (327 nodes). No failing test reproduced. The hosted `test: failure` is UNRESOLVED without a node/log; no speculative source repair.
- Executed suite inventory for `packages/maistro-core/tests`: PASS (16543 nodes, no duplicate evidence); shipped-surface truth: PASS.
- Read full codec, immutable identity constructors and codec tests. Runtime import search finds only codec -> identity and a whitelist import; no production caller. Accepted ADR-081226-a66b preserves Run lifecycle authority; ADR-083126-5e62 preserves trusted-base gate authority. No fake wiring or new authority is an acceptable reconciliation.
- Existing tests establish representation only: handcrafted evidence tags, fixed fingerprint, synthetic identity strings. Production materialization/authorization are not proven by those fixtures. Live PostgreSQL validation completed below.

## Live database and adjacent tests

Executed at starting HEAD (only this documentation changed), with 1800-second tool timeouts:

- Verified running `maistro-postgres` container, resolved local credentials in-process without recording them, verified `issue1893_aed7f8d7` did not exist, then created that dedicated disposable database. No existing database reused or truncated.
- `DATABASE_URL=<disposable DSN> uv run alembic upgrade head`: PASS, actual empty-to-head chain 001 through 063, including admission-generation migration 055. PostgreSQL 18.6.
- Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` targeted the same disposable DB; `MAISTRO_REQUIRE_PG_LEGS=1` enforced non-skipping.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-aed7-pg.xml`: **204 passed, zero skipped**, 1.54s.
- JUnit recorded production/raw backend PID pairs **363689/363690** (unbound), **363691/363692** (bound), **363693/363694** (acknowledged), each on `issue1893_aed7f8d7`, server `172.20.0.2/32:5432`. Each state persisted exactly one row, read independently through both pools. Bound inserts satisfied the real paired-identity CHECK. Escaped-surrogate corruption was injected into each TEXT snapshot and safely rejected by both readers.
- Independent final SQL session **363696**: migration version **063**, `SELECT count(*) FROM task_idempotency` = **0**. Disposable DB retained locally; no production data touched.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1919 passed, 310 skipped, 6 warnings**, 50.56s (2229 nodes). This separate run had no PG DSNs; skips are not durability evidence. Warnings were adjacent aiosqlite worker threads encountering closed event loops, not failed assertions.

## Acceptance audit

| Criterion | Evidence and limits |
| --- | --- |
| Exact frozen/slotted header; decode/encode interfaces; fresh flat mapping | Source inspection and executed header/round-trip/fresh-mapping/immutable-constructor tests pass. |
| Named columns, UUID `.hex`, signed timestamps, matching header | Executed storage-UUID, scalar type/range, header mismatch and missing-column tests pass; real named-column INSERT/SELECT pass. Physical `request` maps to DTO `request_snapshot`, matching migration 055 rather than inventing a new column. |
| Supported format only; no fallback from unknown format | Parametrized unknown-format tests pass, including bool/float/string/NULL and forged supported headers. |
| Strict JSON TEXT and safe typed errors | Duplicate/nonobject/bare-nonfinite, excessive nesting, lossy numeric and invalid-Unicode tests pass; actual PG corruption injection passes. Tests assert safe messages and suppressed parsing chains. |
| Legacy bound/unbound/partial without guessed identity | Executed legacy tests pass, including one-sided pairs, receipt-only, unreadable evidence and pair without receipt. A bound pair lacking receipt cannot satisfy the prerequisite canonical DTO; it remains explicit partial evidence, not a fabricated receipt. |
| Header evidence survives full-decode failure | Expiry/fingerprint preservation tests pass. No clock or incoming fingerprint enters the codec; consumer replacement/409 precedence is not this B2 leaf. |
| Snapshot bytes/tags and stored fingerprint preservation | Round-trip/tag tests pass for canonical snapshots and fixed fingerprints. Real original-model fingerprinting, evidence-json serialization and `model_of`/`model_of_json` materialization end-to-end: **UNVERIFIED**; handcrafted tags cannot establish that integration. |
| Raw and production pool compatibility | 204 no-skip passes on newly migrated PG18; distinct sessions, one persisted row per case, zero final admission rows. |
| Run JSONB object rather than double encoding; arbitrary context materialization | **UNVERIFIED** through a production caller: this staged codec has no Run INSERT or materializing consumer. |
| Real principals, authorized Workspace/Project and registered Graph kinds | **UNVERIFIED** through admission; fixtures use synthetic strings and do not exercise authorization. |
| Stage limits and canonical execution authority | Source remains representation-only; no production caller. Goal -> Graph -> Run -> NodeRun -> Attempt preserved. ADR-082526-7f02 also forbids retro-writing admission provenance as dispatch identity. No SQL mutation/HTTP/queue/assessment/scope/deletion/activation change made. |
| Inventory and required validation | Inventory, ruff, format, scoped mypy, Vulture and shipped-surface pass. Required provenance fails. Full integration CI and reported hosted test failure remain **UNVERIFIED**. |

## Final disposition and next action

**BLOCKED.** No evidence-backed source repair or Vulture ledger amendment was identified. Only `docs/testing/1893-repair-handoff.md` changed. No tests added or altered, no inventory delta, no pre-fix or mutation failure claimed. Existing inventory notes were inspected but not rewritten as fresh proof.

Required provenance rejects the candidate reachability rows in `quality/reachability-baseline.json` and `quality/reachability-dispositions.json`. Resolving that requires owner coordination and an already-landed trusted-base authorization under the two-merge rule, or a separately authorized real consumer integration. Neither is permitted in this B2 repair. Do not repeatedly redispatch the unchanged slice as a speculative test repair: obtain the actual failing CI node/log and resolve trusted-base coordination first.

No push, GitHub mutation, grant/gate change, branch deletion or production activation performed. Local documentation commit is a handoff, not integration approval. Residual risks are the required provenance failure, inactive production contract, unproven materialization/authorization/full CI, and unresolved hosted test failure.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base coordination and actual failing-node evidence}`.
