# Issue #1893 bounded repair validation

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting head: `b31c35270937f0e73be9783cdbd088e6cd31a912` (verified).
- Supplied develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree initially clean; no incoming edits to salvage.
- Production review scope: `packages/maistro-core/src/maistro/tasks/admission_codec.py`,
  `packages/maistro-core/src/maistro/runs/admission_identity.py`, adjacent identity,
  snapshot and SQL consumers; their two admission test files and relevant ADRs.
- Gate evidence scope: supplied job `1cec0f49a9d6433bb8840313d5981914`
  check logs, captured dispatch context, CI workflows and existing quality ledgers.
- Only planned write: this validation/handoff note; change production/tests or the
  permitted vulture ledger only if execution establishes an in-scope defect.
- No GitHub mutations, activation, policy selection, or reachability grants.

## Initial evidence and assumptions

Read repository AGENTS.md and supplied check-0 through check-4 logs. Driver reports
successful dependency sync, lint, formatting and inventory; admission tests report
311 passed, 3 skipped. These do not establish PostgreSQL durability.

The dispatch contains a generic `test: failure`, not a failing test traceback.
Assumption: reproduce focused tests and exact-debt gates before attempting a fix.
Previously reported reachability authorization failures are not presumed repaired.
No develop sync conflict is present, so no fetch/merge is planned. Captured issue
text explicitly forbids production activation or fabricated runtime callers.

## Execution results

- Both supplied base and local `origin/develop` resolve to
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1323 reviewed identities / 1323 findings; 0 unclassified. No vulture
  ledger amendment is justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`:
  FAIL (exit 1). Both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` have unauthorized new reachability dispositions
  and unauthorized new unreachable-module baseline entries. This reproduces the
  prior blocker against the exact supplied integration base; other subgates pass.
- Code inspection confirms these are deliberately inactive contracts, not a
  reachable admission path. Wiring fake callers or granting on this candidate
  would violate the issue and trusted-base policy. This round cannot authorize
  that change; no reachability ledger/gate edits will be made.

- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -q -x`:
  PASS, 201 passed / 3 PostgreSQL tests skipped, 204 collected nodes.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  PASS, 2 source files.
- Source import search finds no production consumer of these contracts (only
  the codec's DTO import and the vulture whitelist). Captured PR #1945 review
  findings about whitespace and numeric precision have regression coverage in
  the existing focused tests, which pass in this execution.

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16467 collected nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-reachability.py`: PASS as a candidate-ledger
  match, 1396 production modules / 171 unreachable; **not** authorization.
- `uv run python scripts/check-reachability-dispositions.py`: PASS as a
  candidate-ledger match, 50 groups / 171 modules; **not** authorization.
- Captured PR #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355`
  check-runs list has `exact-debt-ledger` as its only failed check, with no
  traceback in `output`. No new remote status/log fetch was performed. The
  separately dispatched generic `test: failure` remains unexplained, not
  assumed fixed by focused success.
- Read accepted ADR-082826-b601 (one canonical consumer; explicit eligibility)
  and ADR-082526-7f02 (immutable admission provenance; Attempt-owned dispatch),
  plus docs/quality-gates.md. No reconciliation requires production changes:
  this leaf remains pure serialization, not a scheduler or admission authority.
- PostgreSQL 18.6 is available locally with current role `dev`. Both required
  test DSNs were initially unset. Plan: create a fresh dedicated database for
  this job before any fixture that truncates scratch tables.

## PostgreSQL execution (not inherited evidence)

Fresh database `maistro_1893_1cec0f49`, PostgreSQL 18.6, local Unix socket,
role `dev`. Executed:

```bash
createdb maistro_1893_1cec0f49
DATABASE_URL=postgresql:///maistro_1893_1cec0f49 uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_1cec0f49 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_1cec0f49 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  packages/maistro-core/tests/tasks/test_admission_codec.py -q -x \
  --junitxml=/tmp/maistro-1893-1cec0f49-pg.xml -o junit_family=legacy
psql -d maistro_1893_1cec0f49 -Atc \
  'SELECT version_num FROM alembic_version; SELECT count(*) FROM task_idempotency; SELECT count(*) FROM canonical_runs;'
```

All exit 0. Real chain upgraded empty database through 062. Focused suite:
**204 collected, 204 passed, 0 skipped**. Post-suite SQL: revision 062,
0 admission rows, 0 canonical Runs. Existing tests inject each binding state
(unbound/bound/acknowledged), insert bound TEXT parameters into the real table,
read through independently connected raw/production-codec pools, assert one
persisted row, exact decoded record/mapping equality, then inject escaped
surrogates into each snapshot column and require typed, sanitized rejection.
JUnit properties parsed after the run:

| State | Production PID | Raw PID | Persisted admission rows |
| --- | ---: | ---: | ---: |
| unbound | 2763952 | 2763953 | 1 |
| bound | 2763955 | 2763956 | 1 |
| acknowledged | 2763977 | 2763978 | 1 |

All session identities name `maistro_1893_1cec0f49`; server address/port are
NULL because both DSNs use the local Unix socket. PIDs differ in every pair.
No destructive migration/downgrade test was run after the runtime tests.

Adjacent package validation used the same three PG environment variables plus
`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`:

```bash
uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q --timeout=60
```

PASS: **2225 passed, 3 skipped, 6 warnings**, 2228 collected nodes, 84.26s.
Warnings were aiosqlite worker threads reporting `Event loop is closed` in
`tests/runs/test_sqlite_store.py`; no failing test. Skipped adjacent tests are
not counted as proof. The fresh database is retained for inspection; final
focused-suite counts above precede this broader adjacent suite.

## Acceptance disposition

| Issue requirement | Executed evidence / limit |
| --- | --- |
| Exact frozen/slotted header and shared typed interfaces | Source inspected; focused mypy and header/DTO contract tests pass. |
| Named scalar columns, signed timestamps, strict storage UUID hex; reject mismatched header | Focused format/header/schema/UUID cases pass. Unknown versions cannot fall through to legacy. |
| No guessed legacy identity; distinguish bound, unresolved and partial/receipt-only rows | Existing legacy cases pass, including whitespace corruption and missing receipt evidence. Header tests preserve expiry/fingerprint despite full-decode failure. |
| Strict TEXT JSON; duplicate/nonobject/nonfinite rejection; safe decode errors | Focused rejection tests pass, including nested numeric precision, recursion, Unicode corruption, suppressed exception context and validated-hash scope. |
| Fresh SQL mapping and all immutable snapshot bytes | All three state round trips pass against mappings and migrated PG; migration-055 binding shape assertions pass. |
| Tagged nonfinite evidence and unchanged fingerprint | Existing tagged-snapshot tests pass. Production evidence serializer was read; codec deliberately does not materialize models. End-to-end TaskResponse/Run materialization and original-model fingerprint validation are **UNVERIFIED in this round**. |
| Raw and production pools read identical TEXT snapshots | Three real-PG cases pass with distinct sessions above, no skips. These are storage fixtures, not positive authorized admission scenarios. |
| Run JSONB payload remains an object via text cast | No Run insert was added or changed; codec PG tests do not insert a Run. This exact payload acceptance assertion is **UNVERIFIED in this round**, not inferred from the codec test. |
| No clock, SQL mutation, HTTP mapping, queue policy or live assessor change | Inspected codec has none; no production/test source is changed in this repair. Production import search confirms the intended inactive stage, not runtime readiness. |
| Meaningful regression/pre-fix evidence | Existing tests assert independently the storage binding shape and inject corrupt storage bytes, rather than only mock returns. Mutation/pre-fix execution was **not repeated** this round. |
| Inventory and local quality checks | 16467-node core inventory passes; ruff/format/mypy/vulture pass. No tests/counts changed, so no inventory delta is required. |
| Unchanged required integration CI, no self-authorized debt | **FAIL**: exact-debt provenance has four unauthorized additions across the two reachability ledgers. Full required integration CI was **not rerun**; generic dispatched `test: failure` remains UNRESOLVED. |
| Coordinated staging / activation ownership | Assigned branch/head honored. No activation, policy selection, independent admission authority, GitHub mutation or closure action. Production activation remains blocked. |

## Handoff

Verdict: **BLOCKED**, not integration approval. No speculative code or ledger
repair was justified: the permitted vulture ledger already exactly matches.
The reproduced blocker is at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`, enforced by
`.github/workflows/vulture-ratchet.yml:77`. A candidate-only ledger or grant
cannot authorize itself. The integration owner must resolve the staged-leaf
reachability/authorization boundary on the trusted base before this branch can
pass; adding fake imports or activating the future consumer here is forbidden.

Only changed file this round: this validation note. Existing implementation,
tests, ledgers and gates are preserved. Local commit required before handoff.
Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 1
blocking gate. Next: authorized integration-owner resolution, plus an actual
failing CI test log if the dispatched `test: failure` still applies.

