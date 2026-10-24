# Issue #1893 repair — ddf0c26e

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `953d5bb9f6459f8b8ad1eea732661058243c0e20`;
  supplied develop base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- One issue only: #1893. Inspect existing admission codec, immutable admission
  identity types, their adjacent tests, relevant ADRs and CI gate configuration.
- Potential repair files: those two production modules and adjacent tests only
  if fresh evidence establishes a defect; Vulture ledger only if the explicitly
  requested scan establishes reviewed debt. This report is the checkpoint.
- No GitHub actions, ref updates, scheduler changes, reachability ledger/grant
  edits, or production activation. No pre-existing uncommitted work to salvage.

## Initial evidence and assumption

Read supplied dispatch issue body and prior result. Driver check-0 through
check-4 report dependency sync, lint/format, 346 passed / 3 skipped focused tests,
and inventory success. These are driver evidence, not new executions by me.
The prior result reports an unresolved trusted-base reachability gate failure;
no specific hosted `test: failure` traceback was supplied. Assume this is a
focused validation/repair round, not authorization to fabricate reachability or
choose the unresolved production activation policy. Staged B2 codec behavior
is distinct from downstream C/F2 admission behavior.

## Fresh checkpoint

- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`
  exited 1: two NEW unreachable modules and two NEW dispositions lack
  already-landed authorization (`maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec`). Log: `/tmp/1893-ddf-provenance.log`.
- Verified local `origin/develop` resolves to the exact supplied base above.
  There is no develop-sync conflict in this checkout. No fetch/merge attempted.
- Requested exact Vulture command exited 0: 1322 reviewed identities / 1322
  findings, no new or stale identities. Log: `/tmp/1893-ddf-vulture.log`.
  Thus no Vulture ledger amendment is justified by evidence.
- Codec module explicitly has no production consumer; its pure implementation
  only constructs DTOs/mappings. Existing tests exercise schema-constrained
  bound/unbound shapes independently of encoder/decoder agreement. Neither
  unit results nor its future-consumer disposition establish activation.

## Validation executed at the starting source SHA

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`
  -> 2064 passed, 310 skipped, 6 warnings in 49.56s (2374 collected nodes).
  Log: `/tmp/1893-ddf-tests.log`. Warnings are aiosqlite worker threads attempting
  callbacks after event-loop shutdown; no failing test was reproduced.
- `uv run ruff check .` -> passed.
- `uv run ruff format --check .` -> 3301 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`
  -> no issues in 2 source files.
- `uv run python scripts/check-shipped-surface-truth.py` -> complete.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  -> 16567 collected/unique identities; no duplicate evidence; inventory matches.

## Architecture reconciliation

Read repository AGENTS, quality-gate policy and accepted ADRs
ADR-083126-5e62 (trusted-base authority), ADR-082526-7f02 (immutable admission
provenance versus Attempt identity), ADR-082826-b601 (one canonical consumer).
Keep `Goal -> Graph -> Run -> NodeRun -> Attempt`; DTO construction is neither
admission nor authorization. No scheduler/consumer/re-export is added to make
an inactive slice appear reachable. Candidate ledger entries cannot grant
permission to themselves. The Vulture-specific repair exception does not
permit reachability authorization changes.

## Acceptance accounting

All test names below belong to the executed `test_admission_codec.py` unless
otherwise stated. They prove direct codec behavior, not reachable admission.

| Criterion | Fresh evidence / limitation |
| --- | --- |
| Immutable header and exact named-column DTO decoding | Existing constructor, scalar/header mismatch, missing-column and immutable identity tests passed in the scoped run. |
| Fresh flat v2 mapping and byte-faithful snapshots | `test_v2_round_trip_preserves_all_snapshot_bytes` (unbound/bound/acknowledged) and `test_encode_returns_a_fresh_flat_mapping` passed; task/run columns asserted independently of decode agreement. |
| Owner UUID only hex at storage; strict UUID input | `test_owner_token_is_hex_at_storage_only` and strict generation UUID cases passed. |
| Legacy bound/unbound/partial, no invented identity | Binding distinction, receipt-only, missing-receipt, unreadable/whitespace evidence and expired-header tests passed. |
| Header remains available despite snapshot/binding failure | Both header-preservation tests passed; codec takes no clock or incoming fingerprint. |
| Unsupported formats/schema and invalid scalar headers fail closed | Unknown format, missing-column and invalid-scalar tests passed. |
| Strict JSON and safe diagnostics | Duplicate/nonobject/nonfinite, excessive nesting, lossy numeric evidence, surrogate, and error scope/chain tests passed. |
| Tagged program_context and unchanged stored fingerprint | Tagged nonfinite round-trip test passed. Production model materialization / fingerprint generation is UNVERIFIED by this codec-only evidence. |
| Real raw/production-pool contrast on migrated PostgreSQL | Three state cases skipped; live migration chain, DB session identities and final SQL row counts UNVERIFIED this round. No skipped or SQLite leg counted as durability. |
| Run JSONB remains object, explicit authorized principals/Workspace/Project/Graph | UNVERIFIED by this round; codec tests build DTOs, not production admission. No activation claim. |
| No SQL/HTTP/queue/claim/policy changes in B2 | This round changes only this report; production codec inspection shows mapping conversion only. Downstream replacement/409 precedence remains C/F2 evidence, not B2 acceptance. |
| Focused quality and test inventory | Commands above pass; no tests added or changed, so inventory delta is zero and no new inventory note is required. |
| Unchanged integration CI and reachability authorization | FAILED trusted-base gate (four concrete violations); full hosted CI and reported hosted test traceback remain UNVERIFIED. |
| Known pre-fix/mutation failure | No new regression repair or test addition this round, and no mutation execution claimed. Existing binding assertions inspect independent migration-055 shape. |

## Disposition

BLOCKED, not integration-ready. No actionable Vulture finding or focused test
failure was found; no speculative production or ledger edits made. Existing
unauthorized reachability rows are preserved, not discarded or reauthorized.
Campaign owner must resolve the trusted-base authorization prerequisite via
the reviewed process and supply the actual hosted `test` traceback if it still
fails. Do not repeat an identical validation loop expecting a different grant
result. Live PostgreSQL proof and unchanged full integration CI remain required.

Changed file: this report only. No tests, inventory, gates or ledgers modified.
Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 1 blocking
gate; next: owner-level authorization/CI evidence handoff. Local commit required
before stopping; no remote actions authorized or performed.
