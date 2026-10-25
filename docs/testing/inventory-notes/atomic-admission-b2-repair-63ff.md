---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair snapshot — job 63ff

Assigned head: `726b321e47d4fed6045bb2ee1ff0a264ecb78874` (clean).
Assigned comparison base: `34795962548a33f6b6f7e1234dcea201a9df96ef`.
Only issue #1893 is in scope. Frozen repair file scope: admission_codec.py,
test_admission_codec.py, this note, and quality/vulture-baseline.json only if
actual scanner evidence requires its explicitly permitted amendment. Adjacent
identity types, migration 055, pool fixtures, ADRs and gates are inspection-only.
No GitHub mutations, production activation, new authority, or unrelated history
repair is authorized. The large inherited base diff is not this repair's scope.

Initial driver logs inspected: check-0 dependencies successful; check-1 ruff
passed; check-2 format passed; check-3 201 passed/3 skipped (not DB proof);
check-4 inventory 15610 passed. These do not establish acceptance alone.
Ambiguity: older prior findings may already be repaired at assigned head;
assumption is to reproduce before modifying code or ledgers. Activation/ownership
coordination remains distinct from local writer handoff.

Reproduced result: exact requested vulture scan passes (1328 reviewed / 1328
findings), so no ledger amendment is justified. Ratchet provenance with assigned
base fails: merge base af799688335f has neither authorization for the two new
unreachable modules (`maistro.runs.admission_identity`,
`maistro.tasks.admission_codec`) nor their dispositions. These are not vulture
identities, and changing those ledgers/grants or adding fake callers is forbidden.
The historical binding defect is already fixed at codec line 290 and covered by
unbound/bound/acknowledged mapping and real-pool tests. Prior result 97f2 confirms
that repair was in the incoming head; its old prose finding is stale.

Read accepted ADRs 081226-a66b, 081426-1f7c, 082526-7f02, 082826-b601,
082826-d9f5: immutable admission provenance and the canonical execution
spine/store/consumer remain unchanged. The issue's storage wording is reconciled
to migration 055: physical `request` TEXT maps to DTO `request_snapshot`, and
bound `task_id` equals the receipt identity (not a newly invented work ID).

Executed on assigned production source:
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3166 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, 15610 nodes (no added tests).
- Created dedicated disposable DB `maistro_1893_63ff` on PostgreSQL 18.6;
  `DATABASE_URL=postgresql:///maistro_1893_63ff uv run alembic upgrade head`
  applied the real chain from empty to revision 060 (including 055).
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_63ff`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=/tmp/maistro-1893-63ff-focused.xml`:
  **204 passed, no skips**. SQL inspection afterwards: revision 060, **0**
  admission rows, **0** generation IDs, **0** Run IDs in the admission table.

- Real-pool test session PIDs (production/raw): unbound **3630738/3630739**,
  bound **3630742/3630746**, acknowledged **3630750/3630752**. All target
  `maistro_1893_63ff` over the Unix socket. Each observed exactly **1** scoped
  admission row through both independent pools, then removed it. Properties
  are in the JUnit XML above, which also records the exact collected nodes.
- Same DB environment: `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **2118 passed, 3 skipped, 5 warnings**.
  Warnings are aiosqlite worker callbacks after event-loop closure. No skip is
  counted as durability proof. Final admission-table counts after this larger
  suite: **3 rows, 0 distinct generation IDs, 2 distinct Run IDs** (legacy
  adjacent-test residue). Dedicated DB retained for inspection.
- `uv run python scripts/check-reachability.py`: passed against candidate
  ledger, 1363 production modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: passed against
  candidate ledger, 171 dispositioned modules.
- `uv run python scripts/check-promotion-surface.py`: passed, 74 tolerances.
- `uv run python scripts/check-radon-baseline.py`: passed, 137/137.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, 1328/1328.
- `RATCHET_BASE_REV=34795962548a33f6b6f7e1234dcea201a9df96ef uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**, reachability and disposition
  authorization for both admission modules absent at merge base af799688335f.
  Candidate-ledger checks passing above do not negate this required failure.

## Acceptance audit

All ten named prospective codec tests executed in the 204-pass focused run:

| Criterion | Executed evidence / boundary |
| --- | --- |
| V2 flat named mapping and byte-faithful canonical snapshots | `test_v2_round_trip_preserves_all_snapshot_bytes` for unbound/bound/acknowledged; fresh mapping tests; live migration-055 CHECK accepts bound task_id=receipt_id |
| Owner tokens UUID hex only at storage | `test_owner_token_is_hex_at_storage_only`, strict generation-ID cases; safe error messages |
| Legacy bound, unbound, partial distinct without identity invention | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, whitespace cases |
| Expired supported legacy exposes evidence without a clock or missing ID invention | `test_expired_legacy_header_does_not_invent_missing_identity` |
| Header survives malformed snapshot | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| Header survives partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unknown format cannot fall through to legacy | `test_unknown_format_cannot_be_reinterpreted_as_legacy`; header mismatch/scalar tests |
| Tagged nonfinite data retains fingerprint | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` checks stored evidence tags, not production model materialization |
| Strict TEXT snapshots and safe typed errors | `test_invalid_and_duplicate_json_is_rejected`; nested, lossy-number, surrogate and predecoded-input cases |
| Raw/production pool equivalence against real schema | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` in all three states, no skips; same DB and distinct sessions verified |

Source inspection confirms frozen/slotted header, six error codes, validated
scope hashes, header/full-decode separation, signed scalar validation, #1851
constructors and named storage columns. The decoder receives no clock or incoming
fingerprint and performs no SQL, HTTP, queue mutation, assessment or fingerprint
recalculation. ADR execution/store/authority constraints are preserved.

**UNVERIFIED / not satisfied as production integration:** both modules remain
unreachable from production entrypoints. The focused tests use literal evidence
and identity strings, not an authorized Workspace/Project admission or registered
Graph execution. They do not prove new snapshot materialization via
`model_of`/`model_of_json`, original-model fingerprint ordering, a Run JSONB object
write, live replacement/409 precedence, concurrency, dispatch or crash safety.
Those integration criteria require the separately owned consumer/backend work;
no fake consumer or activation is added to satisfy a scanner. Full required hosted
CI and the dispatch's unnamed `test: failure` are **UNVERIFIED**; the supplied
check logs and this round's focused/adjacent runs do not reproduce that failure.
No new regression test was added and no pre-fix/mutation run is claimed this round.

## Disposition and next action

**BLOCKED**, not merge-ready. Only this inventory/handoff note changes. Existing
codec repair and tests were preserved; there is no evidence justifying another
production patch or a vulture amendment. Required provenance cannot be fixed by
this lane without violating the no-grant/no-fake-wiring constraints. Owner must
provide the coordinated trusted integration/authorization path and specific
failing `test` log before another repair attempt; repeated validation cannot
resolve that prerequisite. No GitHub action or deployment is authorized.

Progress: checked 1 assigned issue, validation done 1, skipped 0 issues,
errors 1 required gate; next is owner coordination, not another speculative edit.
