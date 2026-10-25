# Issue #1893 repair checkpoint (fa52096e)

## Frozen scope

- Assigned issue: #1893 only; worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `0228240e1d2834f38ed8f675918f839dc0633ff4`; supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean; no incoming changes to salvage.
- Inputs: captured `dispatch-context.json`, job `check-0.log` through `check-4.log`, prior result `687ea5da39244baaa6e705896b6cfefb/result.json`. No GitHub mutations or refreshed issue/PR enumeration.
- Inspection scope: admission codec and immutable identity DTOs, their tests/inventory notes, relevant architecture/ADRs, and CI definitions/quality gates needed to reproduce the reported `test` failure and provenance blocker. Only evidence-backed repair within this scope is authorized. Ledger edits restricted to the explicitly permitted vulture repair; no reachability grant edits.

## Initial evidence and assumptions

Driver logs: dependency sync, Ruff, formatting and suite inventory pass; focused tests report 311 passed and 3 skipped. These are not live PostgreSQL proof. Prior result reports a provenance gate failure and says the captured CI test failure has no traceback and belongs to another SHA; neither claim is assumed current.

Ambiguity: a generic `test: failure` is supplied without a failing node/traceback. Inspect the captured evidence and reproduce relevant tests; do not invent a code fix or modify gates merely to obtain green status. This lane is a staged codec repair, not authorization for production activation or a new admission authority.

## Reproduced result: BLOCKED

The mandatory provenance gate fails against the supplied base. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are newly unreachable modules without previously landed authorization, and both have unauthorized new dispositions. Existing candidate additions are at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:604-614`. The exact-debt-ledger workflow runs provenance before Vulture (`.github/workflows/vulture-ratchet.yml:77`). Passing Vulture does not repair this failure.

The requested Vulture command reports exactly 1323 findings / 1323 reviewed identities and succeeds. There are no unbanked identities to amend. No source defect was reproduced and no ledger, grant, whitelist, gate or source change is justified by these results.

Captured failed-check objects were extracted once to `worker-captured-failures.json` in the job directory. The only captured failed `test` check names head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the assigned head; its title/summary/text are null. Attribution to this candidate is **UNRESOLVED**. No remote refresh, speculative sync or merge: the assigned checkout has no conflicts.

## Architecture and reachability

Read the supplied repository instructions, documentation map, quality-gate policy, accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle), ADR-083126-5e62 (trusted-base quality authority), codec and prerequisite identity source, adjacent tests, and applicable CI workflow sections. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. A DTO is neither admission nor authorization.

A production-source import search finds only codec-to-identity and Vulture-whitelist imports. `admission_codec.py:50-53` explicitly states there is no production consumer. Unit tests cannot prove runtime reachability; adding an artificial import would not repair that. B2 forbids activation, so the reconciliation is to leave this staged contract blocked pending separately reviewed consumer integration or trusted-base authorization, not to silently expand the scope.

## Executed validation

Source remained at the starting SHA; only this note changed. Validation commands used 1800-second timeouts. Logs below live in `/home/dev/maistro/jobs/fa52096e7bea4ca6932f0e2689db5e07/`.

| Command | Outcome / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 identities; `worker-vulture.log` |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized modules and two dispositions; `worker-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s` | 314 nodes: 311 passed, 3 skipped in 1.53s; `worker-focused.log` |
| `uv run ruff check .` | PASS; `worker-quality.log` |
| `uv run ruff format --check .` | PASS, 3277 files; `worker-quality.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; `worker-quality.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16467 nodes, no duplicate evidence; `worker-quality.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `worker-quality.log` |

The independent driver logs were also inspected, not treated as proof of skipped legs. Docker lists running PostgreSQL 18 containers, but no dedicated disposable database was provisioned after the mandatory blocker reproduced. Both required test DSNs are unset; existing databases were not mutated. No database/session/row-count evidence is claimed.

## Acceptance audit

PASS below denotes the executed codec/type contract, **not** reachable admission behavior.

| Criterion | Executed evidence or limitation |
| --- | --- |
| Frozen/slotted header and shared interfaces; strict scalar/UUID validation; six typed failure codes with validated scope and safe errors | Source inspection plus scalar/schema, strict-storage UUID, scope, snapshot-error and immutable DTO tests PASS. |
| Fresh flat named-column mapping; v2 unbound/bound/acknowledged round trip preserves canonical snapshot bytes | `test_v2_round_trip_preserves_all_snapshot_bytes` (three states), `test_encode_returns_a_fresh_flat_mapping`, and `test_owner_token_is_hex_at_storage_only` PASS. Binding assertions at test lines 134-137 independently enforce the migration-055 pair rather than relying on encode/decode agreement. |
| Legacy unbound/bound/partial remain distinct without invented work identity; receipt-only and missing-Run fail partial | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, bound-pair-without-receipt, unreadable-evidence and whitespace tests PASS. A pair without receipt cannot satisfy the prerequisite binding constructor and remains explicitly partial. |
| Header survives malformed snapshot and partial binding; preserves expiry/fingerprint without clock or incoming fingerprint | `test_expired_legacy_header_does_not_invent_missing_identity`, `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails`, and `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` PASS. |
| Reject mismatched headers, invalid scalar headers and unknown formats | `test_header_scalar_mismatch_is_invalid_header`, `test_unknown_format_cannot_be_reinterpreted_as_legacy`, schema and invalid-scalar tests PASS. |
| TEXT snapshots reject duplicate keys, nonobjects, bare nonfinite values and invalid original evidence with suppressed unsafe chains | `test_invalid_and_duplicate_json_is_rejected`, nesting, lossy-number, non-UTF8 and predecoded-value tests PASS. Corruption is injected at the row boundary; valid Unicode and exact-number cases also PASS. |
| Preserve tagged nonfinite evidence and original fingerprint | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` PASS for handwritten tags. Original-model fingerprint -> evidence-json -> `model_of`/`model_of_json` production materialization is **UNVERIFIED**; these fixtures do not prove it. |
| Raw/production pools read identical TEXT from the same real migrated disposable PostgreSQL DB | **UNVERIFIED**: three skips at test line 470, no configured DSNs. No live migration, durability, session identity or final SQL counts claimed. |
| Actual Run INSERT remains a JSONB object, not a JSON string; real authorized principals, Workspace/Project and registered Graph kinds | **UNVERIFIED** by synthetic DTO tests. No admission or Run INSERT is performed by B2. |
| No SQL mutation, live `_assess`, scope utility, HTTP/queue, deletion-policy or new execution authority changes | Source inspection: codec accepts mappings and constructs DTOs/mappings only. This round changes only this evidence note. C/F2 expiry replacement and HTTP 409 precedence remain outside B2 and are not claimed. |
| Inventory, focused pytest/lint/type checks and unchanged full required integration CI | Focused checks PASS above; full required integration CI **UNVERIFIED**, mandatory provenance FAILS. No new tests or inventory delta in this round. |
| Coordinated stack ownership and activation choices | Isolated repair lane only; wider coordination/activation remains **UNVERIFIED** and is not authorized by passing tests. |

No repair or test addition was justified, so no new pre-fix/mutation proof is claimed and no inventory note is needed. Existing work is preserved.

## Handoff

Only changed file: this note. Commit locally; do not push. Resolving this blocker requires an authorized owner to supply a trusted base with separately landed reachability authorization or a separately reviewed real consumer integration consistent with #1845. A test repair additionally needs candidate-qualified failing-node/traceback evidence. Repeating this dispatch with identical inputs cannot resolve either dependency.

Progress: checked 1, done 0, skipped 0, errors 1 (mandatory provenance), next: owner action on trusted-base integration and candidate-qualified CI evidence.
