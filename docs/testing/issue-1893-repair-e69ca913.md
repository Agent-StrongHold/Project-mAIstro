# Issue #1893 repair checkpoint (e69ca913)

## Frozen scope

Only issue #1893, at assigned head
`054ee378d4584212b917351f199e121fbd92e8a5`, base
`3c761d14db944a727fa0744444bc67cfe36d49f7`, in `auto-1893`.
Inspect the admission codec, identity DTO, adjacent tests, applicable ADRs and
CI gates, and the supplied dispatch evidence. This report is the only planned
edit unless independent validation demonstrates a scoped defect. No tests added;
no inventory delta. The initial worktree was clean, with no salvage necessary.

## Initial evidence

Driver check-0 through check-4 logs show dependency sync, lint, format, focused
201 passing / 3 skipped tests, and inventory 16466 passing. They are not live
PostgreSQL evidence. The prior result is BLOCKED, not a successful repair.
The local `origin/develop` and merge base both resolve to the exact supplied
base. No develop sync conflict exists. No GitHub fetch or mutation performed.

Read issue body and prior result from the supplied immutable dispatch snapshot;
inspected the complete codec and codec tests. The codec explicitly remains
inactive pending consumer C. Test imports/whitelist imports cannot establish
production reachability, and this lane cannot activate C to bypass a gate.

Ambiguity: the dispatch supplies a generic `test: failure` without an
assigned-head traceback. Check-run objects require inspection of the frozen
JSON shape (initial extraction found source paths but no wrapped check list).
Assumption: do not guess code/scanner repairs from a failure label.
The attempted `docs/adr/README*` search did not resolve; skipped that nonexistent
path and read `docs/README.md` instead.

## Independent blocker result

Executed with 1200-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 findings, zero unclassified. No Vulture ledger amendment justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules and new dispositions without trusted-base authorization. Candidate accounting is 171 modules versus 169 authorized on base.

The frozen check-run arrays show `test` failure only at #1855 head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`; #1945 head
`fcc8b437f209a35aa68a61d6f0a5387414938355` has successful `test` and failed
`exact-debt-ledger`. Both have null output summaries/text. The assigned-head
failed test remains UNRESOLVED; no additional remote enumeration is warranted.

Read accepted ADR-081226-69ee, ADR-082526-7f02 and ADR-083126-5e62,
plus the identity DTO and all adjacent identity tests. Reconciliation: preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and immutable admission provenance;
a candidate cannot authorize itself. The Vulture exception does not permit
reachability authorization edits. This is an external coordination blocker,
not a merge conflict or a demonstrated codec defect.

## Focused independent validation

All commands used a 1200-second timeout and unchanged Python source at the
starting SHA:

- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: 204 nodes, 201 passed, 3 skipped in 1.50s. Skips at `test_admission_codec.py:470` require both PostgreSQL DSNs.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16466 nodes, zero duplicate evidence.
- `uv run python scripts/check-reachability.py`: PASS candidate accounting, 1396 production modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: PASS candidate accounting, 50 groups / 171 modules.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-promotion-surface.py`: PASS, 74 tolerated modules.
- `git diff --check`: PASS.

Production Python import search found only codec-to-identity and Vulture
whitelist imports. This corroborates, rather than fixes, the failed provenance
gate. Candidate reachability entries are at `quality/reachability-baseline.json`
lines 131 and 147 and dispositions lines 606-613. No authorized consumer was
found or invented.

## Acceptance evidence and limits

| Criterion | Executed evidence or limitation |
| --- | --- |
| Exact shared interfaces, frozen/slotted header, error codes and named columns | Source inspected; header/schema/format/mismatch tests passed. |
| Strict storage UUID hex, signed timestamps, immutable #1851 constructors | Owner/generation/scalar and adjacent identity tests passed. |
| Fresh flat mapping and optional binding | Three round-trip state tests passed, independently asserting task_id = receipt_id and paired run_id. Real SQL constraints UNVERIFIED this round. |
| Legacy bound/unbound/partial, receipt-only, no invented identity | Existing legacy tests passed. Pair lacking receipt is partial because #1851 requires receipt identity; no receipt is inferred. completed_at grants no authority. |
| Header preserved despite malformed snapshot/partial binding; unsupported formats fail closed | Named header expiry/fingerprint and format tests passed. Header takes no clock or incoming fingerprint. Consumer expiry/409 behavior is outside B2 and UNVERIFIED. |
| Strict JSON, permitted tagged evidence, safe errors and validated scope | Duplicate/nonobject/nonfinite, nesting, decimal-loss, Unicode and error tests passed. Tagged fixtures survive without fingerprint recalculation. |
| Actual evidence-json producer and model_of/model_of_json materialization | UNVERIFIED: focused tests use hand-built snapshots, not actual model materialization. |
| Raw and production pools on the same migrated disposable DB | UNVERIFIED: all three PG cases skipped. No DB was provisioned after the trusted-base blocker reproduced; no session/row counts or durability claim. |
| Run JSONB object, explicit authorized principals/Workspace/Project and registered Graph kind | UNVERIFIED: DTO fixtures do not exercise Run insertion or admission authorization. |
| No new SQL mutation, HTTP/queue/assessor/scope/policy or execution authority | Source inspected; this round changes this report only and preserves staged inactivity. |
| Focused tests, lint, format, mypy, inventory | PASS as listed; no tests added and no inventory note adjustment needed. |
| Unchanged required integration CI and prohibition on self-authorizing unreachable code | FAIL trusted-base provenance; Vulture and candidate accounting PASS. Full CI and assigned-head reported test failure UNVERIFIED. Existing unauthorized reachability edits remain unresolved, untouched. |

No scoped runtime failure reproduced, so no speculative repair, mutation-test
claim, or ledger amendment was made. This report is a blocked handoff, not a
cosmetic code repair or integration approval.

**BLOCKED.** Next: obtain independently reviewed trusted-base authorization or
coordinated consumer integration outside B2's scope, plus an assigned-head
failed-test traceback if the test failure label persists. No gate weakening,
GitHub mutation, push, merge, issue closure or destructive Git operation.

Progress: checked 1, done 0, skipped 0, errors 1 (trusted-base blocker).
Only changed file: `docs/testing/issue-1893-repair-e69ca913.md`.
Commit this report locally; leave the worktree clean.
