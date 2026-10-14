# Issue #1893 repair checkpoint

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
