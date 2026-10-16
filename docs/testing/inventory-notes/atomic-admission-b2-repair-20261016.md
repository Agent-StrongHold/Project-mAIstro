# #1893 repair validation — 2026-10-16

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `491173cee59cbf64edc47b56069714b1669fce9b` (verified); supplied base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Worktree was clean at entry; no incoming edits needed salvage.
- Inputs: supplied `dispatch-context.json`, `check-0.log` through `check-4.log`, and prior result artifact. No remote issue/PR enumeration or GitHub mutations.
- Scope: existing admission codec/identity implementation and adjacent tests, related ADRs/inventory notes, CI test and exact-debt-ledger evidence. Only evidence-backed repairs; no activation or authority changes.
- Ambiguity: dispatch reports generic `test: failure` without a failing test. Treat it as unverified until logs or execution identify a failure. Existing reachability debt cannot be repaired by changing grants/baselines in this lane.

## Progress

Driver logs inspected: sync/lint/format pass, focused tests 346 passed / 3 skipped, inventory 16,567 core nodes with no duplicates. These are not PostgreSQL durability evidence. Prior result is BLOCKED, with no hosted failing test traceback. Existing codec explicitly documents no production consumer; current tests independently assert the migration-055 binding shape but use synthetic DTO identity strings. No production repair is justified by the supplied generic test label. No tests added or removed; independent gate execution follows.

## Reproduced gate result

Executed with a 1200-second timeout at the starting HEAD:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS; 1,322 reviewed findings, zero unclassified. No Vulture amendment is warranted.
- `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1); 169 -> 171 unreachable modules/dispositions. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` lack already-landed authorization. All other wrapper checks pass.
- The supplied base resolves to the exact expected commit. No develop-sync conflict exists.
- Source import search confirms there is no production codec caller; the identity module is imported only by the inactive codec and Vulture whitelist. This is not runtime reachability.

Read accepted ADRs 081226-a66b, 082526-7f02 and 083126-5e62: retain canonical execution ownership, immutable admission provenance, and trusted-base authorization. Candidate banking cannot approve this slice. Neither prohibited activation nor an in-branch grant is an acceptable repair. The generic hosted `test: failure` remains UNRESOLVED: inspected driver logs have no failing traceback, and focused core tests do not cover the separate CI `test` job (`.github/workflows/ci.yml:504,597-620`). Stop investigating that ambiguity without a supplied failing node/log.

No production/test/ledger/gate change is justified by current evidence.

## Fresh focused validation

Executed at source SHA `491173cee59cbf64edc47b56069714b1669fce9b`, all with a 1200-second command timeout:

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s`: **346 passed, 3 skipped**, 349 nodes, 2.82 seconds. All skips are real-pool cases at `test_admission_codec.py:470`, missing both required DSNs.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two source files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16,567 nodes, no duplicate evidence.

No tests added/removed; inventory delta is zero. No fresh pre-fix or mutation experiment is claimed. This is a documentation-only handoff, not a source repair.

## Acceptance audit

| Criterion | Executed evidence / limitation |
| --- | --- |
| Exact shared interfaces, frozen/slotted header, six decode codes | Source inspected at `admission_codec.py:132-270`; header/scalar/mismatch tests pass. Codec takes neither clock nor incoming fingerprint. |
| Exact immutable V2 record, fresh flat named-column mapping | Three `test_v2_round_trip_preserves_all_snapshot_bytes` states and fresh-mapping test pass; independent assertions at `test_admission_codec.py:134-137` check task/Run storage shape. |
| Storage-only UUID hex; signed timestamps; prerequisite constructors | Owner-token, generation, invalid-scalar, lease and acknowledgement tests pass. Bound receipt consistency is enforced at `admission_identity.py:291-292`. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run remain distinct; no fabricated identity | Legacy binding and receipt-only/one-sided/missing-receipt/unreadable/whitespace tests pass. Pair-without-receipt is explicitly partial because the prerequisite binding requires receipt identity; no identity is invented to satisfy it. `completed_at` authority test passes. |
| Header survives malformed snapshot/partial binding; unknown formats fail closed | Expiry/fingerprint preservation, scalar inversion and seven unsupported-format cases pass. C's inclusive-expiry/replacement/409 decisions are outside this codec and **UNVERIFIED** here. |
| Strict TEXT snapshot parsing and safe errors | Duplicate/nonobject/bare-nonfinite/invalid JSON, excessive nesting, lossy numbers and Unicode tests pass; suppression of unsafe parsing chains and validated scope tested. |
| Tagged nonfinite/program_context evidence and stored fingerprint preserved | Tagged snapshot, Unicode and exact-number tests pass; tags remain intact. Actual `evidence_json` serializer, `model_of`/`model_of_json` materialization and fingerprint computation from the original model are **UNVERIFIED** by these synthetic-tag tests. |
| Raw and production pools against same real migrated disposable PostgreSQL | **UNVERIFIED this round**: three skipped cases. No migration-chain execution, session identities, persisted/final row counts or durability proof claimed. |
| Run payload stored as JSONB object, explicit authorized principals/Workspace/Project/registered Graph | **UNVERIFIED**: codec fixtures use synthetic strings; constructing an immutable DTO proves no authorization or Run insertion. |
| No SQL mutation, HTTP mapping, queue/claim/_assess/scope/policy changes | Full codec inspected: mappings only. This round changes only this note, preserving `Goal -> Graph -> Run -> NodeRun -> Attempt`. |
| Inventory/focused lint, format, types and tests | Fresh commands above pass except explicit PG skips; no inventory delta. |
| Reachable production behavior and unchanged required integration CI | **NOT PROVEN**: actual provenance gate fails for both inactive modules. Full hosted CI and the reported hosted test failure remain **UNVERIFIED/UNRESOLVED**. Vulture is already exact; no amendment needed. |
| Coordinated staging/ownership and activation prerequisites | Assigned head respected; external coordination/activation decisions **UNVERIFIED**. No activation, integration, rollout, merge or closure authorized. |

## Handoff

Changed file: only `docs/testing/inventory-notes/atomic-admission-b2-repair-20261016.md`.
Verdict: **BLOCKED**. Local commit records evidence only; it is not merge approval.

Next input required: an assigned-head hosted failing test node/traceback, and a separately authorized trusted-base reachability resolution or coordinated real consumer integration. Repeating unchanged checks or editing the already-exact Vulture ledger cannot resolve this blocker. Do not invent a caller or modify reachability grants/gates in this lane.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate. Residual risks: inactive production slice, unresolved hosted failure, and explicitly unverified database/materialization/authorization criteria. No GitHub mutation, fetch, merge, baseline/grant change or discarded work.
