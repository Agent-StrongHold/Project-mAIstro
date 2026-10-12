# Issue #1893 repair checkpoint — 56c51282

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `2fda6b36f5ab18881d462a1ff87c38b0157477ef`; supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Only issue #1893; inspect existing admission codec/identity implementation, adjacent tests and their inventory notes, relevant ADRs and CI gates. No independent implementation or activation.
- Initial tree clean; no salvage required. Snapshot source: supplied dispatch-context.json, no GitHub enumeration or mutations.
- Candidate edits restricted to evidence-based repairs in the admission codec/identity and adjacent tests, their notes, this report, and (only if actual scan requires it) the explicitly permitted Vulture ledger. No reachability ledger/grant edits.

## Initial evidence and assumptions

- Driver check-0..4 logs: dependency sync, ruff and formatting pass; focused tests 201 passed / 3 skipped; suite inventory passes (16466 nodes).
- Prior result at 2fda6b36 reports BLOCKED on reachability provenance; prior PostgreSQL and other test claims are not treated as current verification.
- Assignment is a writer repair, not the verifier-only instruction. No develop-sync conflict is present; no fetch/merge is presumed authorized or necessary to repair an absent grant.
- Generic `test: failure` has no failing node/log in the prompt. Investigate supplied evidence and execute focused validation; do not guess a cosmetic repair.

## Results

Fresh validation at the starting SHA (logs `/tmp/1893-56c51282-{vulture,provenance,focused}.log`):

- CI-exact `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0, 1323 reviewed identities/findings, zero unclassified. No ledger amendment warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: exit 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` lack trusted-base reachability/disposition authorization (169 -> 171). Other sub-gates pass. `origin/develop` resolves to this exact supplied base; no sync conflict.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`: 201 passed, 3 skipped. Skipped PostgreSQL legs are not durability evidence.
- Read accepted ADR-081426-1f7c and ADR-082526-7f02: preserve Attempt execution identity and immutable admission provenance. Do not invent a caller/authority to evade the staged leaf's missing production reachability.
- Inspected codec implementation, identity constructors and complete codec tests. Existing binding encoding uses receipt_id for task_id, paired with run_id; the independent assertion and migration-backed test already cover the previously repaired bug.

Standing blocker reproduced. Production activation and integration approval are not authorized by this leaf. Continue only bounded acceptance validation; no speculative code or gate changes.

Additional executed checks (same `/tmp/1893-56c51282-` log prefix):

- `uv run ruff check .`, `uv run ruff format --check .`, scoped mypy on both admission source files, `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`, and `uv run python scripts/check-shipped-surface-truth.py`: all exit 0.
- Production import search finds only codec-to-identity and `_vulture_whitelist.py` identity imports. No production codec consumer exists; test imports are not runtime reachability.
- Local PostgreSQL 18.6 available. Verified database `maistro_1893_56c51282` absent; `createdb maistro_1893_56c51282` and `DATABASE_URL=postgresql:///maistro_1893_56c51282 uv run alembic upgrade head` succeeded.
- Inspection mistakes recorded: guessed ADR filename not found; resolved actual filename via local find. Root `migrations` path not found; skipped that search (real Alembic chain used instead). No unresolved git ref was executed.
- Read accepted ADR-083126-5e62: candidate evidence cannot supply its own trusted authorization. The Vulture exception does not permit reachability/grant changes.

## PostgreSQL and regression evidence

At the exact starting source SHA, executed:

```sh
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_56c51282 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_56c51282 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/tasks/test_admission_codec.py \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  -x -q -o junit_family=legacy --junitxml=/tmp/1893-56c51282-live.xml
```

- **204 passed, 0 skipped** (`/tmp/1893-56c51282-live.log`); JUnit records all collected nodes.
- Fresh disposable PostgreSQL 18.6 DB migrated through real chain 001 -> 062, including 055; SQL confirms revision 062. No SQLite/schema recreation or stamping.
- Required nonempty DSNs point to the same database; pg_pool non-None. Production fixture uses `_register_json_codecs`; independent raw pool contrasts TEXT behavior.
- Production/raw session pairs: 210841/210842 (unbound), 210843/210844 (bound), 210845/210846 (acknowledged). All identify `maistro_1893_56c51282` over Unix sockets (address/port NULL). Each test observes exactly one persisted admission row.
- Each PG case injects escaped lone-surrogate JSON into each snapshot TEXT column; both readers reject safely while the header fingerprint remains available. No mock transaction proof claimed.
- Final SQL counts: admissions=0, distinct generations=0, bound Run identities=0; canonical_runs=0, canonical_node_runs=0, canonical_attempts=0. Disposable DB retained.
- Process-only mutation wrapped the production encoder and forced `task_id=None`, without changing files. `uv run python` invoking pytest with `-q -x -k test_v2_round_trip_preserves_all_snapshot_bytes` yielded the expected exit 1: **1 failed, 1 passed, 128 deselected**. The bound case fails independently at `test_admission_codec.py:134`, `None != 'rcpt-1'`. Log: `/tmp/1893-56c51282-mutation.log`. This proves regression sensitivity, not a current defect.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: **1918 passed, 310 skipped, 6 warnings** (`/tmp/1893-56c51282-adjacent.log`). This adjacent run has no PG DSNs; its skips are not durability proof. Warnings concern aiosqlite worker threads using closed event loops in `test_sqlite_store.py`; no unrelated repair attempted.

## Acceptance accounting

| Criterion | Current executed evidence / boundary |
| --- | --- |
| Frozen/slotted header, exact shared signatures, error enum, named columns, strict storage UUID hex and signed timestamps | Production source inspection; focused tests and scoped mypy pass |
| Immutable v2 snapshots, fresh flat mapping, paired binding and acknowledgement | Three-state unit and live PG round-trips pass; independent binding regression assertion catches mutation |
| Legacy bound/unbound/partial, receipt-only and missing receipt evidence without invented identity | Focused legacy tests pass; no clock, cause inference or claim decision |
| Header/full-decode separation; preserve expiry/fingerprint even for malformed snapshots or partial bindings; reject mismatched header | Focused preservation and mismatch tests pass |
| Fail closed for unknown format/schema and invalid data; safe diagnostic chain and validated scope hash | Focused schema/format/duplicate/nonobject/nonfinite/numeric/Unicode and diagnostic tests pass |
| Existing tagged evidence survives without recomputing fingerprint or double decoding | Tagged nonfinite and snapshot round-trip tests pass; fingerprint is passed through unchanged |
| Raw and production pools read identical snapshot TEXT in same real migrated schema | All three PG cases pass, distinct sessions, row counts and zero residue recorded above |
| model_of/model_of_json model materialization and Run JSONB object INSERT | **UNVERIFIED** through this leaf: codec returns immutable text DTOs, not models or Run INSERTs |
| Real authorized Workspace/Project/principals and registered Graph admission through reachable production behavior | **UNVERIFIED**: tests use synthetic identity strings; no production codec consumer exists |
| No SQL mutation, HTTP/queue/assessment/live _assess/scope utility or competing authority changes | Inspected source contains only row/DTO mapping; this round changes only this report. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt preserved |
| Focused tests, lint, format, mypy, inventory | PASS; format 3277 files, mypy two files, inventory 16466 nodes, no duplicate evidence |
| Unchanged full required integration CI | **UNVERIFIED**; no full-tree/service claim. Required provenance **FAILS** against exact supplied base |
| Supplied generic `test: failure` repaired | **UNRESOLVED**: no failing node/traceback supplied; focused and adjacent tests pass |

## Handoff

**BLOCKED**. No evidence-based source repair is indicated by this round. The exact-debt-ledger failure remains the unauthorized reachability/disposition additions at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613`. Resolving that requires owner-governed trusted-base authorization/coordinated integration, not candidate banking, fake consumers or activation in this lane.

Only `docs/testing/issue-1893-repair-56c51282.md` changed. No tests added/removed, so inventory deltas are unchanged and no new inventory note is required. No production/ledger/grant/gate edits, GitHub mutations, fetch or merge. Commit this evidence-only handoff locally; it is neither a successful code repair nor integration approval.

Progress: checked=1, done=0, skipped=0, errors=1. Next: resolve the trusted-base blocker with the owner and supply the actual failing CI test traceback before redispatching repair of unchanged source.

## Bounded rerun — job 82afb913

Frozen issue/worktree/base unchanged; source SHA
`52d8880e0a6d0b112cbbf18562dfe9cc1728bac8`, initially clean. This rerun
updates this existing checkpoint rather than adding another duplicate report.
Inspected repository instructions, codec/identity source and both full test
files, existing inventory note, CI definitions, and accepted ADR-081226-a66b
(lifecycle authority) and ADR-083126-5e62 (trusted-base authority). No new
scheduler, authorization path, production activation or candidate grant is
permitted. The Vulture exception does not authorize reachability changes.

Fresh commands and results (logs under
`/home/dev/maistro/jobs/82afb913533043e9a793e90827858ad7/repair-*.log`):

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities/findings, zero unclassified; no ledger amendment warranted |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL: admission_identity and admission_codec lack trusted-base reachability/disposition authorization, 169 -> 171; other sub-gates pass |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q` | 201 passed, 3 skipped without DSNs |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1918 passed, 310 skipped, 6 aiosqlite closed-event-loop warnings; skips are not durability evidence |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

### Fresh PostgreSQL proof and regression sensitivity

After verifying the database absent, ran `createdb maistro_1893_82afb913` and
`DATABASE_URL=postgresql:///maistro_1893_82afb913 uv run alembic upgrade head`.
PostgreSQL 18.6, real chain 001 -> 062 (including 055), no stamping or recreated
SQLite schema. Then executed:

```sh
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_82afb913 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_82afb913 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/tasks/test_admission_codec.py \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  -x -q -o junit_family=legacy \
  --junitxml=/home/dev/maistro/jobs/82afb913533043e9a793e90827858ad7/repair-live.xml
```

**204 passed, zero skipped.** JUnit records every collected node and database
session evidence. Required DSNs name the same disposable DB; pg_pool is non-None
and uses production JSON codecs. Raw/production session pairs (production first):
unbound 277746/277747, bound 277748/277749, acknowledged 277750/277751. All report
`maistro_1893_82afb913` on Unix sockets, with one persisted admission row per
case. Both pools reject each injected lone-surrogate snapshot while preserving
header evidence. Final SQL: revision 062; admissions, distinct generations,
bound Run identities, canonical Runs, NodeRuns and Attempts each **0**.
Disposable DB retained.

Process-only mutation via `uv run python` wrapped the encoder to set
`task_id=None`, then called pytest with `-q -x -k
test_v2_round_trip_preserves_all_snapshot_bytes`. Expected exit 1: 1 failed,
1 passed, 128 deselected; independent assertion at
`test_admission_codec.py:134` catches the bound regression. No file was mutated.

### Acceptance and remaining blocker

- Exact frozen/slotted header and signatures, enums, named scalar mapping,
  signed timestamps, strict storage UUIDs, immutable DTOs and fresh flat
  encoding: source inspection plus focused tests/mypy pass.
- Legacy unbound/bound/partial/receipt-only and missing receipt evidence,
  unsupported schema/format, header mismatch, expiry/fingerprint preservation:
  focused tests pass. No invented identity or clock/claim/HTTP decision.
- Snapshot duplicate/nonobject/nonfinite rejection, Unicode/numeric safety,
  sanitized diagnostics, tagged evidence preservation without fingerprint
  recomputation or double decoding: focused tests pass.
- TEXT snapshots under raw and production codecs: all three live cases pass
  through the actual migrated schema; mutation proves the binding assertion
  does not merely encode agreement with the current implementation.
- Model materialization with `model_of`/`model_of_json`, Run JSONB object INSERT,
  and authorized Workspace/Project/principal/registered-Graph admission:
  **UNVERIFIED**. These tests use synthetic DTO identity strings, not admission.
- Runtime reachability: production import search finds no codec consumer;
  codec imports identity and the Vulture whitelist imports identity. Test
  imports/exports do not establish production behavior.
- Full integration CI and the supplied generic `test: failure`: **UNVERIFIED /
  UNRESOLVED**. No failing traceback was found in the supplied driver logs or
  extracted captured check-run outputs. `.github/workflows/ci.yml:496-612`
  delegates core to coverage and runs other suites in `test`; core passing is
  not proof that this different CI job passes. No unrelated test changes made.
- Required provenance remains **FAIL**, specifically
  `quality/reachability-baseline.json:131,147` and
  `quality/reachability-dispositions.json:606-613`. Do not use ledger banking,
  fake consumers or activation to hide the missing trusted authorization.

**BLOCKED**, not a repaired source slice or integration approval. Only this
checkpoint changed; zero test additions/removals, so inventory deltas remain
unchanged. No ledger/grant/gate edits, GitHub mutations, fetch/merge or discarded
work. Commit this evidence locally. Checked=1, done=0, skipped=0, errors=1.
Next: owner-governed trusted-base resolution and actual failing CI test evidence;
do not redispatch unchanged-source validation as though it can grant authority.
