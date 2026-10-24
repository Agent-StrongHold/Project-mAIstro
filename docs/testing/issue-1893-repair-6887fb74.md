# Issue #1893 repair checkpoint — job 6887fb74

## Frozen scope

- Assigned issue: #1893 only; writer worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `4ef1d79f7ef64b7e9864d727299aac6aac1545d1`; supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Tree initially clean; no salvage required.
- Review existing `tasks/admission_codec.py`, `runs/admission_identity.py`, their two test files, applicable ADRs/workflows and supplied dispatch/check artifacts.
- Only planned edit is this validation report unless actual scoped failure evidence supports a repair. No ledger/grant/gate changes without applicable authorization.

## Initial evidence and ambiguity

Driver check-0 through check-4 logs report dependency sync, ruff, format and inventory success; scoped tests report 201 passed, 3 skipped. Those skips do not prove PostgreSQL acceptance. The supplied CI label `test: failure` has no traceback in those logs. Prior reachability authorization findings are hypotheses to independently check, not assumed current facts. Staged codec readiness is distinct from activation and independent mergeability; no production wiring is authorized by this issue.

## Local checkpoint

- `uv sync --locked --extra dev`: pass.
- CI-exact Vulture baseline command: exit 0; no unbanked identities requiring the permitted ledger amendment.
- Supplied base resolved before execution. `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: exit 1. Two new unreachable modules (`maistro.runs.admission_identity`, `maistro.tasks.admission_codec`) and their two dispositions lack trusted-base authorization (169 -> 171).
- This is a reproduced policy failure, not missing dependencies. Logs: `worker-vulture.log`, `worker-provenance.log` in the assigned job directory.
- No activation/fake caller or reachability ledger/grant amendment is authorized. The Vulture exception does not authorize changing reachability policy.

- Ruff check and format: pass (3277 files); targeted mypy: pass (2 source files).
- Source import search: only the Vulture whitelist references identity outside the codec; no reachable production codec consumer. This is staged representation, not authorized admission.
- Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-082826-b601 and ADR-083126-5e62. Reconciliation: preserve immutable provenance and the canonical execution spine; candidate evidence cannot self-authorize unreachable code.
- Initial disposable PG setup failed before database creation with `KeyError: POSTGRES_USER`: existing lane container omits that optional setting. Resolve the container's actual role before retrying; no existing DB has been changed.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` without PG variables: **1918 passed, 310 skipped, 6 warnings**, 50.50s (`worker-adjacent.log`). Warnings are aiosqlite worker threads reaching closed event loops; skipped cases are not durability evidence.

## Focused validation result

Actual container role was confirmed with `docker exec auto-1893-pg psql -U postgres -d postgres -Atc 'SELECT current_user, current_database(), version()'`. A fresh disposable database `admission_1893_6887fb74` was then created (no existing DB changed). `uv run alembic upgrade head` passed through the real chain to 062 on PostgreSQL 18.6. Nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` all targeted that database; `MAISTRO_REQUIRE_PG_LEGS=1` prevented durability skips. Credentials stayed private.

`uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused-pg.xml`: **204 passed, zero skipped**, 1.51s. Exact nodes and raw/production backend identities are retained in JUnit. Final SQL reports migration 062, zero admission rows/distinct generations/distinct Run IDs, zero canonical Runs/NodeRuns/Attempts. DB retained for inspection. These tests prove TEXT storage and decode, not authorization or execution.

`uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass, 16466 unique nodes, no duplicates. `uv run python scripts/check-shipped-surface-truth.py`: pass.

Captured CI extraction (`worker-captured-ci.txt`) finds `test: failure` on PR #1855 head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`; PR #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355` has `test: success` and `exact-debt-ledger: failure`. No assigned-head failing test node or traceback is supplied. Attribution is UNRESOLVED; no speculative test repair is justified.

## Acceptance review

All tests below executed at source HEAD `4ef1d79f7ef64b7e9864d727299aac6aac1545d1`; this round edits only this report.

| Criterion | Executed evidence / limit |
| --- | --- |
| Shared signatures, frozen/slotted header, six error codes, validated scope, signed timestamps, #1851 constructors | Source inspection, header/schema/scalar tests and targeted mypy pass |
| Snapshot bytes, fresh flat mapping, strict UUID storage-only owner token | `test_v2_round_trip_preserves_all_snapshot_bytes` (3 states), `test_encode_returns_a_fresh_flat_mapping`, `test_owner_token_is_hex_at_storage_only`, strict generation tests |
| No guessed legacy identity: bound, unbound, partial and receipt-only distinct | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable and whitespace evidence tests |
| Expired legacy header preserves evidence without inventing identity | `test_expired_legacy_header_does_not_invent_missing_identity`; no clock/expiry decision is implemented |
| Expiry preserved despite full snapshot failure | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| Fingerprint preserved despite partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unknown format and mismatched header fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy`, `test_header_scalar_mismatch_is_invalid_header` |
| Tagged nonfinite program_context preserved, fingerprint not recalculated | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change`; hand-tagged evidence only, not actual-model materialization |
| Duplicate/nonobject/bare nonfinite JSON rejected; safe diagnostic chains | `test_invalid_and_duplicate_json_is_rejected`, nesting/lossy-number/surrogate negative tests |
| Real raw and production codec pools read identical TEXT snapshots | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` (3 states); non-None production fixture with `_register_json_codecs`; actual migrations to 062 |
| Named storage columns, paired task_id/run_id, optional acknowledged_at, completed_at not authority | Source inspection, round-trip tests and `test_legacy_completed_at_is_never_read`; migration 055 constraint accepted bound INSERTs |
| No SQL mutation, HTTP serialization, queue/assessment/claim/scope changes | Source inspection: codec takes rows/DTOs only; no production change this round |
| Common CI/gate requirements | Ruff, format, targeted mypy, Vulture, inventory, shipped-surface pass; trusted-base provenance **FAILS** |

PG production/raw backend pairs: 38177/38178 (unbound), 38179/38180 (bound), 38181/38182 (acknowledged), all on `admission_1893_6887fb74`, server `172.17.0.9/32:5432`. Each case asserted exactly one scoped admission row, then injected escaped-surrogate corruption into each of the three TEXT snapshot columns and checked both readers fail safely. Final row/identity counts are zero (`worker-db-evidence.json`). No downgrade test was run.

Independent negative regression probe: in memory only, wrapped `encode_admission_record` to emit `task_id=None`, then called pytest on `test_v2_round_trip_preserves_all_snapshot_bytes`. Bound and acknowledged cases failed at line 134 before relying on decode agreement; unbound passed. Result **2 failed, 1 passed, 128 deselected**, expected pytest exit 1 (`worker-binding-mutation.log`). No source or test was mutated on disk.

**UNVERIFIED / not B2 product proof:** authorized explicit principals and Workspace/Project/registered Graph admission; actual-model `evidence_json` and `model_of`/`model_of_json` materialization; original-model fingerprint computation; Run `json_of(run)` TEXT-to-JSONB object INSERT; C/F2 expiry/409 precedence; unchanged full integration CI; coordination/activation approval. Synthetic fixture identities and hand-written tags cannot establish these criteria. No codec production consumer exists, and adding one to satisfy reachability would exceed this issue's explicit staged scope.

## Blocked handoff

Actual failure: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613` add two unauthorized unreachable modules and their dispositions relative to the supplied trusted base. The CI Vulture exception does not cover these ledgers. No Vulture debt or codec defect was reproduced; no cosmetic production/ledger change is justified.

Owner action needed: resolve the admission reachability authorization through the protected-base workflow before integration, then provide a current-head failing test traceback if test repair is still requested. Do not activate a consumer or self-authorize a grant as a workaround. No fetch/merge was needed for a conflict (tree started clean and no conflict exists); no GitHub mutations performed.

Changed file: `docs/testing/issue-1893-repair-6887fb74.md` only. No test inventory delta because no tests/counts changed. `git diff --check` passed. Local commit is evidence handoff only, not approval.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 unresolved provenance blocker (initial PG setup error recovered). Next: owner authorization resolution and exact current-head CI failure evidence.
