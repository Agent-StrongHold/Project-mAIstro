# Issue #1893 repair checkpoint — 77ab3416

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893` in the assigned worktree.
- Starting source: `dcf2f9f2bcc6a402890d75c10d8e23ba01e2c9a7`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree was clean; no salvage required.
- Review scope: existing admission codec, identity DTOs, their two test files,
  related accepted ADRs, CI commands and supplied job evidence. Only this report
  is initially authorized for editing; any code repair requires actual failure
  evidence. No ledger/grant/gate edits except the expressly permitted vulture
  ledger repair if that scanner establishes a retained identity mismatch.
- No GitHub mutations, production activation, new consumer or execution authority.

## Initial evidence and assumptions

Read repository instructions and the full primary issue body from the supplied
`dispatch-context.json`. The issue permits a staged typed codec only and expressly
prohibits making an unwired slice green through baseline/grant edits. The writer
assignment authorizes local work, not activation or resolution of owner policy.

Driver logs: check-0 dependency resolution succeeded; check-1 ruff passed;
check-2 format passed (3277 files); check-3 reports 201 passed, 3 skipped;
check-4 suite inventory passed (16466 nodes). These are supplied evidence, not
fresh worker executions. Database acceptance remains unproven by skipped tests.
The `test: failure` dispatch has no failing node or traceback in those logs.
Prior provenance failure must be reproduced before proposing a repair.

## Worker validation

- `uv sync --locked --extra dev`: passed.
- CI-exact `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed identities and findings. No ledger amendment is indicated.
- Resolved the dispatch base before execution. `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: **exit 1**. Reachability and disposition counts increase from 169 to 171; both admission modules lack trusted-base authorization. All other subchecks passed.
- `uv run ruff check .`, `uv run ruff format --check .`: passed (3277 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: 1918 passed, 310 skipped, 5 aiosqlite thread/event-loop warnings. No test failure reproduced; PG skips are not durability evidence.
- Source import search confirms no production codec consumer; only the codec and Vulture whitelist refer to admission identity. Production reachability is not established by these tests.
- Confirmed the existing lane PostgreSQL container's role and server (PostgreSQL 18.6), then created new disposable DB `admission_1893_77ab3416`. `uv run alembic upgrade head` applied the real chain to 062. No existing DB was changed.
- With nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, and `MAISTRO_TEST_DATABASE_URL` targeting that DB and `MAISTRO_REQUIRE_PG_LEGS=1`, ran `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused-pg.xml`: **204 passed, zero skipped**. Logs and exact node/session identities are in the assigned job directory (`worker-migrate.log`, `worker-focused-pg.log`, `worker-focused-pg.xml`).
- Final SQL (`worker-db-counts.log`): revision 062, zero admission rows/distinct generations/distinct bound Runs, and zero canonical Runs/NodeRuns/Attempts. Disposable DB retained for inspection.
- This independently reproduces the prior blocker. The Vulture-only repair exception cannot authorize reachability ledger changes or a new production consumer. No test or codec repair was justified.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16466 unique nodes, no duplicates. `uv run python scripts/check-shipped-surface-truth.py`: passed.
- Binding regression probe, in memory only: wrapped `encode_admission_record` to omit `task_id`, then ran the three `test_v2_round_trip_preserves_all_snapshot_bytes` cases. Bound and acknowledged cases failed at test line 134; unbound passed (2 failed, 1 passed, 128 deselected). This independently establishes sensitivity to the previously repaired SQL CHECK violation. No file was mutated; log: `<job>/worker-binding-mutation.log`.

## Acceptance review

All fresh execution used source SHA `dcf2f9f2bcc6a402890d75c10d8e23ba01e2c9a7`;
this round changes only this report. Focused JUnit records all 204 exact nodes.

| Criterion | Evidence and limits |
| --- | --- |
| Frozen/slotted header, required shared signatures and six error codes; validated hash, signed timestamps, strict UUID hex | Inspected codec definitions and #1851 DTO constructors; header/schema/scalar/UUID negative tests and mypy passed |
| Snapshot bytes and fresh flat SQL mapping | Three `test_v2_round_trip_preserves_all_snapshot_bytes` states and `test_encode_returns_a_fresh_flat_mapping` passed |
| Owner token hex only at storage, safe error diagnostics | `test_owner_token_is_hex_at_storage_only`, invalid UUID and snapshot diagnostic tests passed |
| Legacy bound/unbound/partial distinct, no invented receipt or work identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable and whitespace-evidence cases passed |
| Expired supported legacy header retains scalars, independent of full decode | `test_expired_legacy_header_does_not_invent_missing_identity`, expiry-with-invalid-snapshot and fingerprint-with-partial-binding tests passed |
| Unknown format and mismatched header fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy`, `test_header_scalar_mismatch_is_invalid_header` passed |
| Tagged nonfinite evidence and stored fingerprint preserved | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` passed; these are handwritten tags, not actual-model materialization proof |
| Strict TEXT JSON: duplicates/nonobjects/bare nonfinite rejected | `test_invalid_and_duplicate_json_is_rejected`, deep nesting, lossy number, and surrogate-corruption tests passed |
| Same migrated schema, raw and production JSON codec pools | Three `test_raw_and_production_pool_codecs_read_identical_text_snapshots` states passed with required PG legs and non-None production pool; real INSERT accepted migration-055 binding constraint |
| Named SQL mapping, acknowledged_at, completed_at is not authority | Source review, round trips, `test_legacy_completed_at_is_never_read` passed |
| No SQL mutation, HTTP/queue/assessment/scope/clock or new authority | Codec accepts mappings/DTOs only; no production changes in this round; source search confirms no runtime consumer |
| Focused tests, inventory, lint, formatting, applicable typing | Fresh commands above passed; no new tests, hence no inventory-count delta |
| Required integration gates | Vulture and shipped surface passed; trusted-base provenance **failed**; unchanged full integration CI is **UNVERIFIED** |

Database session pairs (production/raw backend PIDs): unbound 38849/38851,
bound 38852/38853, acknowledged 38855/38856, all on
`admission_1893_77ab3416`, `172.17.0.9/32:5432`. Each case asserted one stored
admission row and tested escaped-surrogate corruption in each of three TEXT
columns through both pools. No downgrade test ran. These are codec storage
checks with synthetic identities, not authorization or execution evidence.

**UNVERIFIED:** real-model `evidence_json` encoding and `model_of`/`model_of_json`
materialization, original-model fingerprint generation, Run `json_of(run)`
TEXT-to-JSONB object INSERT, authorized explicit principals/Workspace/Project
and registered Graph admission, C/F2 replacement/409 precedence, production
activation and coordination approval. Those are not established by this staged
codec's tests, nor can a new consumer be introduced under this repair scope.

## Actual CI evidence and blocked handoff

Extracted captured check-runs from the supplied dispatch without fetching or
re-enumerating GitHub: `test: failure` belongs to head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (#1855); head
`fcc8b437f209a35aa68a61d6f0a5387414938355` (#1945) has `test: success` and
`exact-debt-ledger: failure`. There is no assigned-head failing test node or
traceback in the supplied check logs. Current-head failure attribution is
**UNRESOLVED**; speculative test edits are not justified.

Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-082826-b601 and
ADR-083126-5e62. Reconciliation: preserve canonical Goal -> Graph -> Run ->
NodeRun -> Attempt execution, immutable admission provenance and protected-base
quality authority. A passing codec test or candidate ledger cannot authorize
runtime admission or a reachability exception.

The independently reproduced blocker is at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`: two new unreachable modules
and dispositions lack trusted-base authorization. Resolving it requires owner
action through the protected-base authorization process, not candidate edits,
fake runtime imports, gate weakening or the Vulture-only exception. No sync
conflict exists; no fetch/merge or GitHub mutation was performed.

Changed file: `docs/testing/issue-1893-repair-77ab3416.md` only. No production,
test, inventory, ledger or grant edits. This local commit is blocked evidence
handoff, not integration approval. Disposable DB retained for inspection.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 unresolved
provenance blocker. Next: owner resolves protected-base authorization and
supplies a current-head failing test traceback if further test repair is needed.
