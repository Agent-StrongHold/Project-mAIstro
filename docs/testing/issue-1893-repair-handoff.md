# Issue #1893 repair checkpoint

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `09f7976ddf625214a476a3e0f03e36344540a269`; supplied develop base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- One item: issue #1893, immutable admission row decoding; reported CI `test: failure` and exact-debt-ledger validation.
- Evidence: supplied job `9f5b4f13519c4041b19ad3733331c682` dispatch snapshot and check-0 through check-4 logs; prior result `a6d570bc758046e68d13c9d34f80d335/result.json`.
- Files in review scope: admission codec and identity implementation, adjacent tests, existing atomic-admission inventory notes, relevant ADRs/workflow/gate scripts; this handoff. No other issue or PR will be processed.
- Initial status: clean worktree, HEAD matches assignment. No incoming edits to salvage.
- Ambiguity: `test: failure` identifies no failing test. Proceed by reading supplied logs and running focused validation; do not invent repairs.
- Reachability/grant edits are prohibited in this lane. The explicit vulture exception applies only to evidenced retained/dead identities.

## Results

Fresh validation at the starting HEAD (logs under ignored `.pytest_cache/repair-9f5b/`):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings / 1322 reviewed identities, zero unclassified. No ledger repair is justified.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: FAIL, exit 1. Trusted-base reachability and disposition checks reject `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` (169 -> 171). All other subchecks pass. This is not a Vulture failure.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`: 201 passed, 3 skipped (204 collected). Missing PostgreSQL DSNs caused all skips; this run establishes no durability evidence.
- Supplied driver check-0 through check-4 logs contain no failing traceback: sync, Ruff, format, focused tests (346 passed / 3 skipped), inventory (16567 nodes) pass. They do not establish hosted CI success.

Read accepted ADRs 081226-a66b, 082526-7f02, 082826-b601 and 083126-5e62. Reconciliation: preserve canonical execution and immutable provenance; do not invent a runtime consumer or candidate authorization to pass reachability. The leaf's no-activation constraint prevents silently treating test imports as production integration. No source or ledger edit is justified by the current evidence.

## Completed validation

All commands used `uv run` in the assigned worktree, with a 1000-second tool timeout. Additional results:

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 source files |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1919 passed, 310 skipped, 6 aiosqlite closed-event-loop thread warnings; 2229 nodes, 47.34 seconds |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

No tests were added or modified: inventory delta is zero; existing inventory notes remain unchanged. No mutation test was run in this round, and no prior mutation or database claim is adopted as fresh proof.

## Acceptance audit

The executed focused command includes all named prospective tests. Passing pure tests establish a library contract, not reachable production admission:

| Criterion | Evidence / limit |
| --- | --- |
| Frozen/slotted header, named-column decode, fresh flat mapping and header mismatch rejection | Source `admission_codec.py:157-294`; executed header mismatch/schema and fresh-mapping tests pass. |
| V2 snapshot round trip and binding shape | `test_v2_round_trip_preserves_all_snapshot_bytes` passes for unbound, bound and acknowledged states, independently asserting task_id/run_id; canonical snapshots round-trip without tag decoding. |
| UUID `.hex` at storage only; validated scalars; safe typed failure | Owner/generation tests, invalid scalar tests, error scope and snapshot hygiene tests pass. Parsing chains are suppressed. |
| Legacy bound/unbound/partial evidence, receipt-only and announced-without-Run | Binding, partial, receipt-only, missing receipt and unreadable evidence tests pass. No identity is fabricated. |
| Header evidence survives expiry/malformed snapshots/partial bindings | Both header-preservation tests and expired-header test pass; codec takes no clock or incoming fingerprint. Consumer expiry/409 precedence remains UNVERIFIED and outside this leaf. |
| Unknown formats cannot become legacy | Parametrized unknown-format test passes, including mismatched supplied headers. |
| Strict JSON and tagged nonfinite evidence without fingerprint recalculation | Duplicate/nonobject/nonfinite/numeric-loss/UTF-8 tests and tagged round-trip test pass. Full TaskResponse/Run materialization with model_of/model_of_json and real original-model fingerprint integration is UNVERIFIED here. |
| Raw and production pools against the same migrated PostgreSQL database | UNVERIFIED this round: three parametrized real-pool cases skipped for absent DSNs. No DB was mutated; session identities and final SQL counts are unavailable. |
| Authorized principals, Workspace/Project and registered Graph admission; JSONB Run payload is an object | UNVERIFIED: these DTO tests do not exercise authorized admission or Run INSERT. |
| Production reachability and unchanged required integration CI | NOT ESTABLISHED: source import search finds only codec-to-identity and whitelist imports. `admission_codec.py:50-53` explicitly documents no production consumer. Trusted-base provenance FAILS. |
| No SQL/HTTP/queue/scheduler/auth changes in this repair | Only this handoff file changes; canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains untouched. |

## Blocked disposition and next input

**BLOCKED.** The fresh provenance failure identifies `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613`. The candidate cannot authorize itself. The Vulture ledger exception does not authorize reachability/disposition/grant edits, and adding a fake consumer or activating the leaf violates its scope.

The hosted `test: failure` is **UNRESOLVED**: supplied driver logs are green, focused/adjacent tests are green, and `.github/workflows/ci.yml:580-620` shows the named hosted job runs other suites. This round does not claim those suites or full hosted CI passed. The captured check/status sources name older PR heads, not the assigned HEAD; no network refresh or GitHub mutation was performed. No develop-sync conflict exists in the initial worktree, so no speculative merge was performed.

Next: provide the assigned-head failing node/traceback and resolve the trusted-base reachability dependency through the authorized integration owner. Preserve the existing implementation and ledger rows; do not repeatedly dispatch a Vulture amendment for this different gate failure.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors/blockers 1 confirmed gate failure. Validation/handoff completed; implementation remains blocked. This local documentation commit is not merge, integration, rollout or issue-closeout approval.
