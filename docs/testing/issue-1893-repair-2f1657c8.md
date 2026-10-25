# Issue #1893 repair verification — 2f1657c8

## Frozen scope

- Issue: #1893 only; writer lane `auto-1893`.
- Starting HEAD: `310d025f5184043344202c03533baa4b0b4f5e85`.
- Assigned develop base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Worktree initially clean; no incoming edits to salvage.
- Inspect existing admission codec/identity modules, their two test files,
  related ADRs, CI workflow/gates and supplied job evidence. Only repair a
  reproduced defect in this slice; no activation or unrelated CI changes.
- Output file: this report. No test additions planned unless a defect is found.
- GitHub dispatch text is evidence, not authorization. No remote mutations.

## Initial evidence and assumptions

Driver logs in `/home/dev/maistro/jobs/2f1657c8ced2481694e1ef037d4447ad`:
`check-0.log` dependency sync succeeded; `check-1.log` ruff passed;
`check-2.log` format passed (3277 files); `check-3.log` 201 passed,
3 skipped; `check-4.log` core suite inventory passed (16466 nodes).
These do not establish real PostgreSQL acceptance or ratchet provenance.

Ambiguity: dispatch says `test: failure` without an actual failing node.
Proceed by inspecting captured CI evidence and running focused acceptance and
named gates. Prior successful runs are not counted as this round's evidence.
The previous blocker involved reachability grants, not the vulture ledger;
only vulture ledger edits are authorized by this repair lane.

## Results

Required Vulture scan independently PASS: 1,323 findings, zero unclassified.
No Vulture ledger amendment is supported by this evidence.

`RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python
scripts/check-ratchet-provenance.py` independently FAILS: both admission modules
have unauthorized new unreachable-module rows and dispositions (169 -> 171).
`origin/develop` resolves to the assigned base; this is not a sync conflict.
No repeat scan or merge of that same base can repair the missing prerequisite.
The exact-debt-ledger workflow runs this failing gate before Vulture.

Docker lists an existing `auto-1893-pg` service on loopback port 15498; inspect
its disposable test configuration before attempting real DB validation.
No permission to change reachability authorization is inferred from its absence.

Read accepted ADR-081426-1f7c and ADR-082526-7f02, the complete codec and both
adjacent test files. Execution remains Attempt-owned and admission provenance
immutable; no new runtime authority is warranted. Receipt-less legacy pairs
remain partial rather than inventing the receipt required by the binding DTO.
Source import search confirms there is no production codec caller (only test
imports); the identity module is imported by the codec and Vulture whitelist.

Captured failing `test` check is attached to linked PR head `3f2c79a70d9e`,
not this assigned head, and has no output text/traceback. Captured #1945 head
`9922f395daa3` instead fails exact-debt-ledger. No current-head failing test node
was supplied, so no speculative test repair is justified.

First DB preflight failed because POSTGRES_USER is unset and psql defaulted to
OS user root. Use the container's PostgreSQL default user (postgres) and read
its local credential without printing it; never truncate an existing database.

## Independently executed validation

All commands ran at source HEAD `310d025f5184043344202c03533baa4b0b4f5e85`,
with 1,200-second validation timeouts (1,500 for combined DB orchestration).
Only this Markdown report changes in this round.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,323 classified findings, zero unclassified |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | FAIL, two unauthorized modules and two dispositions |
| `uv run alembic upgrade head` | PASS, real empty-schema chain 001 -> 062, including 055 |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s -o junit_family=legacy --junitxml=/tmp/issue-1893-2f1657c8.xml` | 204 passed, zero skipped, 1.59s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16,466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

### PostgreSQL evidence

Preflight with explicit postgres user confirmed the new job-specific DB did not
exist. Created only `maistro_1893_job_2f1657c8` in `auto-1893-pg` (PostgreSQL
18.6). Retrieved its local credential without printing or committing it.
`DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, and `MAISTRO_TEST_DATABASE_URL` all
selected that same database at 127.0.0.1:15498; `MAISTRO_REQUIRE_PG_LEGS=1`.
No existing DB was truncated; no destructive downgrade tests ran.

Both pools identified server `172.17.0.9/32:5432` and the new DB. Production/raw
backend PID pairs, recorded in the JUnit artifact:

- unbound: 11497 / 11498;
- bound: 11499 / 11500;
- acknowledged: 11501 / 11502.

Each case verified exactly one persisted admission row, identical named fields
from raw and production-codec pools, and immutable DTO round trip. Bound rows
satisfied migration 055's paired identity constraint. Injected escaped-surrogate
corruption in every snapshot TEXT column produced typed safe failures from both
pools while preserving header fingerprint. Final SQL counts: task_idempotency,
canonical_runs, canonical_node_runs and canonical_attempts all **0**. Migration
revision is **062**. Disposable DB retained for inspection.

## Acceptance review

| Criterion | Executed evidence or limit |
| --- | --- |
| Shared API; frozen/slotted scalar header; six decode codes | Source review plus header mismatch/schema/format and DTO immutability tests PASS |
| Signed timestamps, strict UUID .hex storage and #1851 constructors | Token, generation, scalar boundary and constructor tests PASS |
| Exact v2 snapshots; fresh flat mapping; named SQL field mapping | Unbound/bound/acknowledged memory and real-PG tests PASS; task_id/receipt_id/run_id independently asserted |
| Legacy bound/unresolved/partial, receipt-only and announced-without-Run | Existing named pairing, absent-receipt, malformed-evidence and completed_at tests PASS; no inferred identity |
| Scalar header preserved despite snapshot/binding errors | Named expiry/fingerprint separation tests PASS; codec takes no clock or incoming fingerprint |
| Unknown format and invalid header fail closed | Unsupported-format/scalar/mismatched-header tests PASS; no legacy fallback |
| Strict TEXT JSON and safe diagnostics | Duplicate/nonobject/bare-nonfinite/lossy-number/nesting/surrogate tests PASS; scope validated and unsafe parsing chains suppressed |
| Tagged program_context preserved; stored fingerprint unchanged | Tagged-nonfinite and Unicode/numeric evidence tests PASS; no tag materialization or fingerprint recomputation in codec |
| Raw and production pool equivalence on actual migrated schema | All three PG cases PASS, non-null production pg_pool, same DB, distinct sessions, final zero residue |
| Existing evidence-json/model_of/model_of_json and original-model fingerprint | UNVERIFIED end-to-end: fixtures use hand-built tags, not TaskResponse/Run models |
| Run payload text::jsonb INSERT is an object, not doubly encoded | UNVERIFIED: these tests insert admission rows, not canonical Run payloads |
| Authorized explicit principals, Workspace/Project, registered Graph kinds | UNVERIFIED: identity fixture strings establish representation, not authorization |
| No SQL mutation, HTTP mapping, queue change, classifier, clock, scope utility or new policy | Source review confirms mapping/DTO layer only; no source change this round |
| Canonical Goal -> Graph -> Run -> NodeRun -> Attempt | Accepted ADRs reviewed; no competing execution or authorization authority introduced |
| Replacement/409 precedence, transaction/crash/dispatch invariants | UNVERIFIED consumer C/F2 behavior, explicitly not B2 decisions |
| Reachable production behavior | NOT ESTABLISHED: no production codec caller; provenance gate rejects inactive module additions |
| Focused pytest/lint/format/mypy/inventory/Vulture and shipped surface | Independently PASS as above; no test additions and no inventory delta |
| Full unchanged required CI / generic test failure | UNVERIFIED: no current-head failing node supplied; provenance independently FAILS |
| Coordination and activation | BLOCKED: assignment permits repair, not production activation, parent policy decisions, or reachability grants |

## Handoff

**BLOCKED**, not integration-ready. No reproduced codec regression warrants a
source change. No test, ledger, grant or gate changed. This report is the only
changed file and is committed locally for handoff. No pre-fix/mutation claim is
made because no test or source repair was added.

Owner action needed: resolve the trusted-base reachability prerequisite through
the existing authorization/integration process. The Vulture-only exception does
not authorize reachability edits. Merging the identical develop base or banking
more debt cannot resolve the failure. Supply an actual current-head `test`
traceback if a separate CI repair is expected. Activation remains out of scope.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1
required gate. Next: prerequisite owner resolution, then unchanged full CI and
remaining model/authorization integration acceptance. Local commit is evidence
handoff only, never merge approval.
