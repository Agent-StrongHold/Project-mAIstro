# Issue #1893 repair — job 62ce7509

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`, worktree `/home/dev/Git/wt/auto-1893`.
- Starting clean HEAD: `e0033539e18ad69da921315f9cfa04760de7442d`.
- Dispatched base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence snapshot: supplied `dispatch-context.json`, `check-0.log` through
  `check-4.log`, and prior job `8b65c8db` result/report. No GitHub re-enumeration.
- Editable files: existing admission codec/identity and their two adjacent test
  files only for demonstrated defects; Vulture ledger only for reviewed scan
  findings; inventory delta note if tests change; this report.
- No source changes or conflict present at entry; no salvage required.

## Initial evidence

Supplied driver logs: dependency sync, lint, format and core suite inventory
pass; focused tests report 201 passed, 3 skipped. Prior report is evidence,
not proof of current behavior. Generic `test: failure` lacks a current-head
traceback in the assignment. Assumption: reproduce named gates and inspect
frozen CI evidence before attempting a source repair. No guessed repair.

## Reproduced blocker

At the frozen source HEAD, exact Vulture scan passed (1323 reviewed identities,
zero unclassified); no ledger amendment is justified. The provenance gate with
`RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7` exited 1:
two new unreachable modules and two new dispositions lack trusted-base
permission. The resolver reports merge base `435dc1937e04`. Worker logs are
`worker-vulture.log`, `worker-provenance.log`, and `worker-focused.log` in the
assigned job directory. Focused tests independently yielded 201 passed, 3
skipped (204 nodes); skips require the two PostgreSQL DSNs.

Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-083126-5e62, repository
instructions, both production modules and their adjacent tests. Reconciliation:
immutable admission representation is not execution or authorization; preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Candidate bookkeeping cannot
provide protected-base permission. The Vulture-only repair exception does not
authorize reachability grants, fake callers, or activation of this staged leaf.

Frozen dispatch CI evidence names a failed `test` at #1855 head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` with no traceback; #1945's captured
head `9922f395daa39249991f18210a6d4da68a3a76cb` passes. Neither is the assigned
HEAD. Current-head test attribution is **UNRESOLVED**. CI's `test` job spans
other packages, root suites and frontends (`.github/workflows/ci.yml:496`);
the focused core pass does not establish that whole job. No speculative source
repair is justified by that label.

## Commands and outcomes

All worker validation commands used a 1200-second timeout, at the starting
source SHA. Logs live in the assigned job directory. Driver logs were also
read, not treated as replacements for worker execution.

| Executed command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1323 reviewed identities, zero unclassified |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | Exit 1; four reachability/disposition authorization violations |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | Exit 0; 201 passed, 3 skipped |
| `uv run ruff check .` | Exit 0 |
| `uv run ruff format --check .` | Exit 0; 3277 files already formatted |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0; two source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0; 16466 nodes, zero copied-file duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0 |
| `rg -n 'admission_codec\|admission_identity' packages/*/src` | Only codec-to-DTO and Vulture-whitelist imports; no live consumer |

The provenance command includes promotion-surface validation, which passes;
reachability/dispositions fail. This is the required exact-debt-ledger step
at `.github/workflows/vulture-ratchet.yml:77`. Existing candidate entries at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` cannot authorize themselves.

## Acceptance audit

These are representation results, not production admission claims. All named
unit tests below executed as part of the 204-node focused command.

| Criterion | Evidence and limits |
| --- | --- |
| Exact frozen/slotted header, shared interfaces and decode codes | Source inspection plus scalar/missing-column/mismatch tests pass; interfaces accept no clock or incoming fingerprint. |
| V2 fresh flat named SQL mapping and exact snapshot round trips | `test_v2_round_trip_preserves_all_snapshot_bytes` passes for unbound/bound/acknowledged; it independently asserts both binding columns and `task_id == receipt_id`. `test_encode_returns_a_fresh_flat_mapping` passes. |
| Strict storage UUID hex, signed timestamps, #1851 constructors | Owner/generation, scalar bounds and DTO validation/immutability tests pass. `test_binding_preserves_original_receipt_identity` rejects envelope/binding disagreement. |
| Legacy bound/unbound/partial, receipt-only and no guessed identity | `test_legacy_binding_unbound_and_partial_are_distinct`, missing-receipt, receipt-only, unreadable/whitespace evidence, and ignored-completed-at tests pass. Both IDs without a receipt remain typed partial evidence, because the canonical constructor requires receipt identity; no identity is fabricated. |
| Header/full-record separation and fail-closed unknown formats | All four named expired-header, malformed-snapshot expiry, partial-binding fingerprint and unknown-format tests pass. Actual expired replacement and mismatch-409 precedence are **UNVERIFIED**, owned by C/F2 rather than B2. |
| Strict TEXT snapshots and safe errors | Invalid/duplicate/nonobject/bare nonfinite, predecoded values, lossy numbers, Unicode and excessive-depth tests pass; tests assert validated scope, safe messages and suppressed unsafe chains. |
| Evidence tags preserved without fingerprint recalculation | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` passes for nan/inf/-inf. Fixtures hand-build tags and pin the stored fingerprint: original-model fingerprinting and real `encode_evidence`/`model_of`/`model_of_json` materialization remain **UNVERIFIED**. |
| Real migrated database, raw/production pool equivalence and Run JSONB object payload | **UNVERIFIED** this round: all three pool cases skip at `test_admission_codec.py:470` for absent DSNs. No disposable DB provisioned; no migration/downgrade, session identities, final SQL counts or durability claims. Existing pool tests insert admission rows, not Run JSONB payloads. |
| Explicit authorized principals, Workspace/Project and registered Graph kinds | **UNVERIFIED**: fixture strings at `test_admission_codec.py:73-78` do not establish authorization. |
| Typed representation only; no SQL mutation, HTTP, queue, assessor, scope or policy changes | Source inspection and caller search show an inactive mapping-only codec. This repair changes documentation only. Production reachability is absent and independently fails the trusted-base gate. No activation or separate execution/authorization path was introduced. |
| Inventory, focused checks and unchanged required integration CI | Focused tests/lint/format/types/inventory/shipped-surface pass above. Required provenance fails. Full integration CI is **UNVERIFIED**, and the generic test-failure attribution remains **UNRESOLVED**. |
| Coordinated stack, prerequisites and ownership | #1851 DTOs are present and tested. Lane grants this repair only; broader stack coordination and activation remain **UNVERIFIED/BLOCKED**. No conflict existed, so conditional conflict-sync instructions did not apply. |

No new test or source repair was added; therefore no inventory delta note or
new pre-fix/mutation claim is appropriate. Existing tests inject corrupt scalar
and snapshot storage values directly, not a mocked transaction. Their passing
results must not be inflated into crash, dispatch or authorization evidence.

## Handoff

**BLOCKED.** Changed file: only this report. No ledger/grant/gate edits, fetch,
merge, push, GitHub mutations, source activation or discarded work.

Next action requires an independently landed, owner-coordinated reachability
authorization followed by authorized base integration, or separately assigned
real consumer integration. A source repair for `test: failure` additionally
requires a failing current-head traceback. Repeating unchanged-source checks
cannot supply either missing input. Do not relax the gates or introduce fake
callers to remove this blocker.

Progress: checked 1, done 0, skipped 0, errors 1 (reproduced provenance blocker).
This local documentation commit is a blocked handoff, not integration approval.
