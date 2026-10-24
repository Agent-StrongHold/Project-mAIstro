# Issue #1893 repair — df27863a

## Frozen scope

- Issue: #1893 only; assigned branch `auto-1893`.
- Starting head: `074785f9db955d06b2a719951d31d1b3ce851c7f`.
- Supplied develop base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Initial worktree clean; no incoming changes to salvage.
- Inspect admission codec, admission identity constructors, adjacent tests, relevant ADRs,
  and exact CI gate definitions. Only evidence-backed repairs to this leaf are in scope.
- Candidate write scope: this report; codec/identity and their tests only if an actual
  defect is reproduced; inventory note if tests change. Vulture ledger only for actual
  reviewed scanner findings under the explicit CI-repair exception.
- No GitHub mutation, production activation, new runtime caller, or reachability
  authorization/ledger changes are authorized.

## Initial evidence and ambiguity

Read supplied dispatch issue body and previous result artifact. Driver logs
`check-0.log` through `check-4.log` report successful dependency sync, Ruff,
formatting, 324 focused passes / 3 skips, and inventory count 16543.
These are driver evidence, not fresh worker execution or PostgreSQL durability proof.
The reported CI `test: failure` has no failing node in the dispatch prompt.
Assumption: reproduce focused behavior and named gates before proposing changes;
passing checks do not justify guessing a repair. Prior reachability authorization
failure must be checked independently; no grant may be invented in this lane.

## Worker results

Fresh worker validation at the starting head:

- Required Vulture command: PASS, 1322 findings / 1322 reviewed identities,
  zero unclassified or never-allowlist. No ledger amendment is warranted.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`:
  FAIL. Both admission modules are unauthorized new unreachable modules and
  dispositions (169 trusted versus 171 candidate). Other wrapper subgates pass.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  PASS, two source files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  324 passed, 3 skipped in 1.90s; skips require both PostgreSQL environment variables.

Read repository instructions, codec/identity source and codec tests, and accepted
ADRs 081226-a66b, 082526-7f02, 083126-5e62. Reconciliation: immutable admission
evidence is neither execution nor authorization authority; candidate ledger rows
cannot authorize their own reachability exception. Production import search finds
only codec-to-identity and Vulture whitelist imports, not a codec runtime consumer.
Both supplied base and local `origin/develop` resolve to the same fixed SHA.
No sync conflict exists, and no new base has been fetched or assumed.

The provenance failure is reproduced, not a missing-dependency failure. It cannot
be fixed under this lane's Vulture-only ledger exception. Live database validation
is considered separately from authorization to integrate the inactive leaf.

## Live PostgreSQL evidence

A fresh disposable database `issue1893_df27863a` was created on the existing local
`maistro-postgres` container after asserting that name did not exist. No existing
database was reused or truncated. Credentials were resolved in-process from the
local container environment and are not recorded here.

- Server: PostgreSQL 18.6 (Debian 18.6-1.pgdg12+2).
- `DATABASE_URL=<disposable DSN> uv run alembic upgrade head`: PASS, actual chain
  from empty through 001 to **063** (including admission migration 055).
- Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` targeted this database;
  `MAISTRO_REQUIRE_PG_LEGS=1` prevented missing configuration from silently skipping.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/issue1893-df27863a-codec.xml`:
  **204 passed, zero skipped**, 1.51s.
- Server identity from both pool connections: database `issue1893_df27863a`,
  address `172.20.0.2/32`, port 5432. Production/raw backend PID pairs:
  unbound 354732/354733; bound 354734/354735; acknowledged 354736/354737.
- Each state persisted exactly one admission row, independently read through raw
  and production-codec pools. The bound/acknowledged INSERTs satisfied migration
  055's paired identity constraint. Injected escaped-surrogate corruption in each
  TEXT snapshot was rejected by both readers without exposing its contents.
- Independent post-test SQL: `alembic_version=063`; `count(*) FROM task_idempotency=0`.
  Disposable schema remains available locally; no production database was touched.

This proves storage representation, not an authorized admission transaction:
fixtures use explicit but synthetic identity strings, not real admitted principals,
Workspace/Project grants or registered Graph kinds. It does not prove Run JSONB
materialization, crash/dispatch invariants or production codec reachability.

## Remaining validation and acceptance audit

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  1919 passed, 310 skipped, 6 warnings in 48.96s (2229 collected). This separate
  adjacent-suite run had no PostgreSQL DSNs; it is not additional PG evidence.
  Warnings were aiosqlite threads encountering closed event loops in
  `test_sqlite_store.py`; no failing assertion was reproduced.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16543 collected identities, zero duplicate identities/copied files.
- `git diff --check`: PASS.
- Read the four supplied linked PR bodies and archived failed-check summaries.
  PR #1945's archived failure is exact-debt-ledger at a different head; the
  archived `test` failure belongs to #1855's head and supplies no failure text.
  Neither establishes a failing test at this assigned head. No new issue or PR
  was dispatched or fetched; linked text did not grant implementation authority.

| Acceptance | Evidence and boundary |
| --- | --- |
| Exact frozen/slotted header and shared interfaces; fresh flat mapping | Source inspection plus passing focused round-trip, mapping isolation and constructor tests. Named columns, not SELECT-star ordering. |
| Strict UUID hex, signed timestamps, supported formats, header agreement | Passing noncanonical/nil UUID, bool/float format, scalar range, missing column and mismatch tests. |
| Legacy bound/unbound/partial distinctions without guessing | Passing bound, unbound, one-sided, receipt-only, missing receipt and unreadable evidence tests. A pair without a receipt cannot satisfy the prerequisite DTO; it remains partial rather than fabricating receipt identity. |
| Header evidence survives full-decode failure | Passing expiry and fingerprint preservation tests; no clock or incoming fingerprint is accepted. Replacement/409 decisions belong to C and are not implemented here. |
| Strict snapshots and safe typed errors | Passing duplicate/nonobject/nonfinite, deep nesting, precision-loss and UTF-8 failure tests, including live PG corruption injection through both pools; safe messages and suppressed chains. |
| Tagged snapshots and unchanged fingerprint | Passing tagged nonfinite and byte-preserving canonical round trips; original-model fingerprinting and model_of/model_of_json production materialization remain UNVERIFIED. |
| TEXT parameters and real migrated two-pool storage | 204 passed without skips on PG18.6 through migration 063; three state-specific INSERT/read round trips with session identities and zero final admission rows. |
| Run JSONB object and arbitrary context materialization | UNVERIFIED end to end: B2 has no Run INSERT or production materializing consumer. |
| Explicit principals, authorized Workspace/Project, registered Graph | UNVERIFIED through production admission; representation tests cannot establish authorization. |
| Scope and canonical execution | No changes to SQL mutation, HTTP, queues, live assessor, scope utilities, lifecycle, authorization or legacy/deletion policy. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt unchanged. |
| Required CI and runtime reachability | Lint/format/scoped mypy/Vulture/inventory/shipped-surface pass; required provenance FAILS. Full integration CI and reported hosted failing-test reproduction remain UNVERIFIED. |

No new tests or code changes were warranted by actual evidence. No inventory delta
or pre-fix/mutation failure is claimed. Existing inventory notes are preserved;
this report records fresh execution rather than rewriting historical evidence.

## Handoff — BLOCKED

Only `docs/testing/issue-1893-repair-df27863a.md` changed. The outstanding required
failure is `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`, enforced by
`.github/workflows/vulture-ratchet.yml:77`. Resolving it requires a separately
reviewed trusted-base authorization/coordination decision under the two-merge
rule, or an explicitly authorized real consumer integration outside B2. Neither
is permitted in this repair lane. Do not repeat candidate ledger edits or add
fake runtime imports to force green.

The named Vulture command is already green; its exception does not authorize
reachability policy edits. Obtain actual failing-node evidence for the assigned
head before another test repair. Database representation now has fresh no-skip
proof, but that does not remove the integration blocker or authorize activation.
No GitHub mutations, grant edits, gate weakening or production activation occurred.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base coordination and actual failing-node evidence}`.
This locally committed report is a blocked handoff, not integration or issue-closure approval.
