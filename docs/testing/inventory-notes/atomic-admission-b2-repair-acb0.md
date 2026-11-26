---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair acb0 — validation checkpoint

Frozen issue: #1893 only. Assigned branch/worktree: `auto-1893`, starting HEAD
`fdfc24fb0f103e3c3008602c19d8c02da56a8d74`, base
`c4bd944393ad7944ac1593013a817b5b22e04dc8`. Initially clean; existing work
preserved. Write scope frozen to the codec, its tests, this note, and the
Vulture ledger only if the required scan identifies actual debt.

Driver logs inspected, not assumed: dependency sync, ruff, formatting and
suite inventory pass; focused tests report 201 passed / 3 skipped. Those
skips are not database evidence. Dispatch and prior result artifact read.
Historic coordination/activation restrictions remain: this assignment permits
local repair, not activation or an independent execution/authorization path.

Current source already encodes bound `task_id=binding.receipt_id`
(`admission_codec.py:291`) and rejects one-sided/mismatched v2 bindings;
migration 055 requires that shape. Prior reported encoder failure is stale.
No source change is justified merely by that old finding.

Fresh required Vulture scan passes (exit 0); provenance against the exact
supplied base fails (exit 1). Logs are in
`/home/dev/maistro/jobs/acb0dacb4c4647a9a63b6494d352da5b/repair-*.log`.
No unbanked Vulture finding exists to amend. Reachability authorization is not
covered by the Vulture-only ledger exception. Docker is unavailable, but native
PostgreSQL is accepting connections; a fresh disposable database will be used
for the existing real-pool tests. No new tests or inventory-count changes.

## Fresh executed validation

All commands used the starting source SHA above. Only this note changed.
Logs, JUnit properties and collected node IDs are retained in the job directory.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1323 reviewed
  identities / 1323 findings. No ledger amendment warranted.
- `RATCHET_BASE_REV=c4bd944393ad7944ac1593013a817b5b22e04dc8 uv run python
  scripts/check-ratchet-provenance.py`: **FAIL**, exit 1. Resolved trusted
  merge base `675db8be6c41`; `repair-provenance.log:20-29` reports NEW,
  unauthorized disposition and unreachable-module identities for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
- `createdb maistro_1893_acb0` followed by
  `DATABASE_URL=postgresql:///maistro_1893_acb0 uv run alembic upgrade head`:
  **PASS**, real fresh migration chain including 055 through 061. No stamping,
  SQLite replacement, downgrade or shared-database mutation. Disposable DB
  retained for inspection.
- With `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both set to
  `postgresql:///maistro_1893_acb0`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, zero skips**. Same paths with `--collect-only -q`: 204 nodes.
- Production/raw pool PID pairs: unbound 3658275/3658276, bound
  3658277/3658278, acknowledged 3658279/3658280 (production first).
  All connect to `maistro_1893_acb0` via Unix socket, with distinct sessions
  and matching database/server identities. Each state persists exactly one
  scoped admission row, read identically through raw asyncpg and production
  `_register_json_codecs`. Final SQL: revision 061, zero admission rows,
  zero distinct generations, zero distinct bound Run IDs after cleanup.
- In-process mutation replaced the encoder's `task_id` with `None`, without
  modifying any source file. `pytest.main` selected the three
  `test_v2_round_trip_preserves_all_snapshot_bytes` cases: expected exit 1,
  **2 failed / 1 passed / 128 deselected**. Bound and acknowledged fail the
  independent storage-shape assertion at test line 134. Thus the tests detect
  the historical regression, rather than merely agreeing with the decoder.
- `uv run ruff check .`, `uv run ruff format --check .`: **PASS**.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **PASS**, 16095 suite nodes, delta zero.
- `uv run python scripts/check-<gate>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: **PASS**.
  Candidate ledger agreement does not override failed trusted-base provenance.

## Acceptance audit and architecture reconciliation

Accepted ADR-081226-a66b and ADR-081426-1f7c preserve the one execution spine;
ADR-082826-b601 requires reviewed canonical consumer eligibility, not incidental
activation. ADR-083126-5e62 prohibits candidate evidence authorizing itself.
Accordingly, no fake caller, new consumer or grant was introduced to make an
inactive contract slice appear production-reachable.

| Criterion | Evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces and error-code values | Source inspection and passing codec/identity tests; header scalar validation and mismatch tests exercised. |
| Fresh named SQL mapping, strict storage UUID hex and signed timestamps | Round-trip, owner-token, UUID, timestamp and missing-column tests pass; migration 055 agrees with bound mapping. Physical `request` TEXT is the DTO's `request_snapshot`, not a new column. |
| Preserve canonical snapshot bytes and fingerprint | Three named v2 round-trip cases pass; tagged nan/inf/-inf tests preserve tags and stored fingerprint; malformed, duplicate, nonobject, bare nonfinite, lossy numeric and Unicode evidence tests pass. |
| Legacy unbound/bound/partial distinguished without invented identity | Named legacy binding test and receipt-only/missing-receipt/one-sided/unreadable-evidence cases pass. A pair without receipt evidence fails typed rather than fabricating a receipt for the #1851 constructor. |
| Expired legacy header preserves evidence without deciding expiry | Named expired-header test passes; no clock or assessment decision in codec. |
| Header expiry survives snapshot failure; fingerprint survives partial binding | Both named separation tests pass, with unchanged scalar evidence. |
| Unknown formats fail closed, never legacy fallback | Named unknown-format tests pass, including forged supported headers. |
| Safe typed errors, validated scope only, no raw snapshot/token in visible exception chain | Error-hygiene tests pass, including corrupt storage and suppressed parsing context. |
| Raw/production pools read identical TEXT snapshots | Three migrated PostgreSQL cases pass with non-null pool, matching DB identities and distinct sessions; escaped-surrogate corruption also rejected through both pools. |
| Existing evidence-json/model_of/model_of_json materialization | Synthetic tag preservation proven; actual model materialization and original-model fingerprint integration **UNVERIFIED**. |
| Representation only: no SQL mutation, queue/HTTP mapping or admission decisions in codec | Source remains mapping-to-DTO translation; no production source changed in this round. |
| Required unchanged CI and reachable production behavior | **NOT PROVEN**: provenance fails. Source import search finds only codec-to-identity and whitelist imports, not a production consumer. Hosted `test: failure` not reproduced by focused tests; full CI **UNVERIFIED**. |

Authorized principal/Workspace/Project/registered-Graph admission, Run
`json_of(run)` TEXT-to-JSONB object insertion, migration downgrade/adoption,
transaction/crash/dispatch invariants and live expiry/409 precedence remain
**UNVERIFIED**. Direct SQL DTO fixtures cannot prove those integration claims.
No activation or parent closeout is implied by the 204 passing tests.

## Handoff — BLOCKED

Changed file: this inventory/evidence note only. No source, tests, quality
ledger, grant or gate edits justified by the reproduced evidence. The Vulture
exception cannot authorize the actual reachability/disposition blocker.
Integration ownership must resolve real consumer wiring or separately landed
trusted-base authorization under existing governance. A failing hosted `test`
traceback is needed before another test-failure source repair is assigned.

Progress: checked 1 issue; done 1 validation/handoff; skipped 0 issues; errors 1
unresolved provenance gate. Next: integration-owner decision and actual hosted
failure evidence. Local commit is a handoff only; no push or GitHub mutation.
