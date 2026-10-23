# Issue #1893 repair checkpoint — 37f73172

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD verified: `87fa3cbe0e01163e0fe4daeb0868daf4a99904f4`; initial worktree clean.
- Dispatch base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Only issue #1893; supplied dispatch-context.json and check-0..4.log are the frozen evidence snapshot. No GitHub refresh or mutations.
- Inspect codec, immutable identity DTOs, adjacent codec tests, existing inventory note, relevant ADRs and CI gate definitions. Candidate changes limited to evidenced codec/test repairs, their inventory note, and this report. Vulture ledger changes only if the explicitly requested scan identifies reviewed debt. No reachability ledger/grant edits.

## Ambiguities and assumptions

The assignment says `test: failure` without a traceback and previously reports an unauthorized reachability disposition. These are hypotheses, not reproduced results. Use supplied logs and execute focused validation before deciding whether code changes are warranted. Production activation is explicitly outside this leaf; do not wire a codec into the live admission assessment merely to satisfy reachability.

## Progress

### Fresh PostgreSQL evidence

Created new disposable database `repair_1893_37f73172` on the already-running `maistro-postgres` container (PostgreSQL 18.6, localhost:5433). `createdb` succeeded without reuse. Credentials were taken from the container environment and not printed or recorded. Set nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, `MAISTRO_TEST_DATABASE_URL` to that same new database and `MAISTRO_REQUIRE_PG_LEGS=1`.

- `uv run alembic upgrade head`: exit 0, real chain from empty database through revision 063 (including 055). No SQLite recreation or schema stamping.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs -o junit_family=legacy --junitxml=/tmp/issue-1893-37f73172-0xtp1s5t/focused.xml`: **204 passed, zero skipped**, exit 0. Both raw and production-codec pools exercised unbound, bound and acknowledged SQL rows, TEXT equality, snapshot corruption and typed decoding.
- Final SQL queries: `alembic_version=063`, `task_idempotency` count 0, `canonical_runs` count 0. Database retained for audit. Logs and session/row-count JUnit properties are in `/tmp/issue-1893-37f73172-0xtp1s5t/`.
- This establishes codec/storage compatibility, NOT authorized admission, Run payload JSONB shape, model materialization or runtime consumer reachability. Tests use fixture identity strings and create no canonical Run. No downgrade tests were run.


Repository instructions and full issue body read. Supplied check-0..4.log report dependency sync, lint, format, 346 passing/3 skipped tests and inventory success; none contains a failing `test` traceback. Prior result.json reports BLOCKED, not a successful repair. Source inspection finds no production consumer: only codec -> identity and the Vulture whitelist import identity. Tagged snapshots in current tests are hand-built JSON, not model materialization evidence. Accepted ADR-082526-7f02 preserves immutable admission history; no competing execution path is justified. The guessed ADR-082826-b601 filename was not found; resolve the actual filename before further reading. Both the dispatch base and local origin/develop resolve to `ac7370141e8e61bd6f352bca35ed0b505104aadb`; no sync conflict exists. Live gates executed: exact Vulture scan passes (1322 findings, 0 unclassified); no ledger amendment is justified. `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` fails with the two unauthorized unreachable modules and their two dispositions; all other sub-ratchets pass. Docker is available with `maistro-postgres` running pgvector/pg18 on localhost:5433; both test DSNs are unset. Will create a uniquely named disposable database before executing PG legs. Read accepted ADR-082826-b601 at its actual `canonical-run-consumer` filename and ADR-062, including its retired run_graph warning. No runtime activation or alternate authority will be introduced.

## Executed validation summary

All commands ran at the starting source SHA; this round changes only this report.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | Exit 0 |
| `uv run ruff check .` | Exit 0 |
| `uv run ruff format --check .` | Exit 0; 3301 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0; 2 files |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` (without DSNs) | Exit 0; 700 passed, 20 explicitly PG-gated skips; not durability proof |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0; 16567 nodes, no duplicate evidence |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1322 reviewed findings, 0 unclassified |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0 |
| `uv run python scripts/check-reachability.py` | Exit 0; 171 unreachable of 1403 modules (candidate ledger matches scan, NOT authorization) |
| `uv run python scripts/check-reachability-dispositions.py` | Exit 0; 50 groups, 171 modules (NOT trusted-base authorization) |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | Exit 1; both admission modules and dispositions unauthorized |
| `git diff --check` | Exit 0 |

### PostgreSQL session evidence

All sessions report database `repair_1893_37f73172`, server `172.20.0.2/32`, port 5432. Independent production/raw backend PID pairs: unbound 371258/371259, bound 371260/371261, acknowledged 371262/371263. Each case independently asserts one persisted admission row; final database queries report zero admission and zero canonical Run rows.

### CI signal reconciliation

The frozen dispatch snapshot's check-runs show `test: success` for this leaf's linked PR #1945 at **80171ce1cff9ca45eaf000bf52569875643a5ba0**, but `exact-debt-ledger: failure`. Its only captured `test: failure` is sibling #1855 at **3f2c79a70d9e1b0b6b6ffc99562cb35db5326828** (check 111298008450); output title/summary/text are null, so it supplies no failing traceback to repair here. #1325 and #2109 captured `test` checks are successful. These statuses are qualified by their own heads and are not current-head/full-CI proof. No remote queries were made. The supplied generic failure is not reproduced by this round's focused validation; its underlying cause remains UNVERIFIED, not declared fixed.

## Acceptance accounting

| Criterion | Evidence / boundary |
| --- | --- |
| Frozen/slotted header; named scalar fields; signed timestamps; supported version only | Source inspection and executed unknown-format, scalar-validation and mismatch tests in `test_admission_codec.py`; 204-case focused run |
| Strict storage UUID hex; fresh flat encode; immutable envelope/record constructors | Executed owner-token, generation-hex, fresh-mapping, v2 round-trip and identity tests |
| Binding without invented identity; partial/receipt-only legacy failures | Executed bound/unbound/partial, receipt-only and missing-receipt tests; no fabricated UUID or receipt on legacy path |
| Header survives malformed snapshots/partial binding; no expiry or mismatch decisions | Executed expiry/fingerprint preservation and unknown-format tests; codec takes no clock/request fingerprint and has no assessment mutation |
| Strict JSON; tags/evidence and stored fingerprint preserved; safe error messages/chains | Executed duplicate/nonobject/nonfinite, nested/precision/Unicode, tagged-snapshot and error-hygiene tests; PG corrupt-TEXT cases also passed |
| Request/receipt/provenance SQL mapping; task/run binding shape | Live migrated SQL INSERT/read/decode for all three states through both pools; revision 055 CHECK accepted the encoded pair |
| Production evidence-json model materialization and Run JSONB object (not double encoding) | UNVERIFIED: fixtures use hand-built tagged JSON; no TaskRequest/TaskResponse/Run materialization or canonical Run INSERT in these codec tests |
| Raw/production pool contrast on same disposable migrated DB | Proven, 3 PG cases, distinct sessions, no skips; real chain empty -> 063; counts above |
| Authorized Workspace/Project/principals/registered Graph positive admission | UNVERIFIED as production admission; tests construct DTO identities only. Activation belongs to another coordinated leaf |
| No SQL/HTTP/queue/live assessor changes or competing scheduler/store/auth path | Preserved; this round changes only the report; source remains inactive |
| Reachable production behavior | NOT PROVEN: import scan finds only codec -> identity and whitelist -> identity; tests and exports are not runtime consumers |
| Inventory, lint, format, applicable mypy and exact Vulture | Passed above; no tests added/removed, so inventory delta is zero and existing notes are unchanged |
| Unchanged full required integration CI / trusted provenance | NOT PASSED: reproduced provenance exit 1; full integration CI not rerun locally; no readiness claim |
| Pre-fix/mutation evidence for new repair | Not applicable: no source/test fix made or claimed; no new mutation experiment |

## Handoff / residual blocker

**BLOCKED.** `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613` retain unauthorized additions relative to the exact dispatch base. `.github/workflows/vulture-ratchet.yml:77` requires the failing provenance gate. No unbanked Vulture identity exists; editing that ledger would not fix this failure. No ledger, grant, gate, source or test was changed.

The previously requested campaign-level resolution remains outside this worker's authority: an independently reviewed authorization must land on the trusted integration base before syncing this branch, or the coordinated integration must supply a genuinely reachable consumer under separately approved scope. This lane must not activate production or self-authorize debt. Re-dispatching the same head without that prerequisite cannot clear this gate.

Changed file: `docs/testing/issue-1893-repair-37f73172.md` only. All evidence above will be committed locally; no push or GitHub mutation. Progress: checked 1 issue, done 0 repairs, skipped 0 issues, blocked 1; next is campaign prerequisite resolution, not another speculative code edit.
