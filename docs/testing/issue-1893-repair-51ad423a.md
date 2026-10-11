# Issue #1893 bounded repair — job 51ad423a

## Frozen scope

- Issue #1893 only; branch `auto-1893`, starting head
  `1662228f318264bb784d15c32913d99072e45b77`, trusted develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence: supplied `dispatch-context.json`, `check-0.log` through
  `check-4.log`, and prior job `62ce7509a2004a5382fea5fbac4753af/result.json`.
- Production review: `maistro/runs/admission_identity.py`,
  `maistro/tasks/admission_codec.py`, their two test modules, adjacent admission
  integration and governing ADRs. Repair candidates are limited to those
  modules/tests and a vulture ledger amendment only if the prescribed scan
  demonstrates retained unbanked identities. No reachability grant/ledger edits.
- No GitHub mutations, remote re-enumeration, or speculative develop sync.

## Initial evidence

The worktree was clean and HEAD matched the assignment. All five supplied
checks passed; the focused test log reports 201 passed, 3 skipped. The previous
result is BLOCKED on trusted-base reachability authorization and unattributed
CI `test` failure. Local `origin/develop` matches the assigned base.

Ambiguity: the dispatch reports `test: failure` without identifying a failing
current-head test. Treat this as unverified until captured logs or local
execution identify it; do not invent a fix.

## Validation and disposition

Frozen CI evidence attributes the failed `test` to #1855 head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the assigned head. The
captured #1945 head is `9922f395daa39249991f18210a6d4da68a3a76cb` and its
recorded failure is `exact-debt-ledger`. Current-head `test` attribution is
UNRESOLVED after inspecting the supplied evidence; no further enumeration.

Both production modules explicitly declare themselves inactive contracts;
the codec has no clock, SQL mutation, HTTP mapping or queue behavior. The
workflow requires trusted-base provenance independently of the Vulture scan.
No activation or competing execution/authorization path will be introduced.
Reproduced: prescribed Vulture scan passes (1323 retained identities, zero
unclassified); no Vulture ledger amendment is warranted. The provenance gate
with the exact assigned base fails on two unauthorized new unreachable modules
and two unauthorized dispositions. It resolves merge base `435dc1937e04`.
Logs: `worker-vulture.log`, `worker-provenance.log` in the assigned job directory.
This confirms the existing blocker, not a guessed scanner finding.

## Executed validation

All execution used the assigned worktree, unchanged production source at the
starting SHA, and 1200-second command timeouts. No prior pass was substituted
for these executions.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1323 reviewed identities, zero unclassified |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | Exit 1; four reachability/disposition authorization violations; promotion-surface passes |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | Exit 0; 204 nodes: 201 passed, 3 skipped; `worker-focused.log` |
| `uv run ruff check .` | Exit 0 |
| `uv run ruff format --check .` | Exit 0; 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0; two source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0; 16466 nodes, no copied-file duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0 |
| `rg -n 'admission_codec\|admission_identity' packages/*/src` | Only codec-to-DTO and Vulture whitelist references; no live consumer |

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62, both
production modules and their complete adjacent test files. Reconciliation:
representation does not authorize execution, mutate admission provenance or
supply trusted-base permission. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`. The Vulture-only repair exception cannot authorize reachability
policy changes. No conflict existed; the conditional conflict-sync instruction
does not apply.

## Acceptance audit

All unit evidence below executed in the focused command above. No mock-return
assertion is counted as transaction, crash, dispatch or authorization proof.

| Criterion | Evidence and limits |
| --- | --- |
| Frozen/slotted header, exact shared APIs and decode codes | Source inspection plus immutability, invalid scalar, missing-column and header-mismatch tests pass. No clock or incoming fingerprint parameter exists. |
| Named SQL mapping, fresh flat parameters, strict UUID hex and signed timestamps | Round-trip tests independently assert binding columns and `task_id == receipt_id`; owner-token, generation, signed bounds and fresh-mapping tests pass. |
| Exact immutable V2 DTOs and original receipt binding | Bound/unbound/acknowledged round trips and `test_binding_preserves_original_receipt_identity` pass. No owner token appears in generated representations. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run | Legacy distinction, receipt-only, missing-receipt and unreadable evidence tests pass. Both IDs without a receipt remain partial because the canonical constructor requires a receipt; none is fabricated. `completed_at` is ignored. |
| Header/full-decode separation, unknown formats fail closed | Expired-header, malformed-snapshot expiry, partial-binding fingerprint and unknown-format tests pass. Actual replacement and 409 precedence remain UNVERIFIED and belong to C/F2, not this codec. |
| Strict TEXT snapshots and safe failures | Duplicate/nonobject/bare-nonfinite, predecoded-value, excessive-depth, lossy-number and Unicode tests pass; errors assert safe messages, validated scope and suppressed chains. |
| Tagged nonfinite context preserved without fingerprint recalculation | Tagged round trips pass for nan/inf/-inf. Fixtures hand-build tags and pin the fingerprint; original-model fingerprinting and real evidence/model materialization remain UNVERIFIED. |
| Raw/production pool equivalence against real migrated PostgreSQL | UNVERIFIED this round: three cases skip at `test_admission_codec.py:470` because both DSNs are absent. No disposable DB was provisioned; no session identities, migration proof or final SQL counts are claimed. |
| Run JSONB object payload, explicit authorized principals, Workspace/Project and valid Graph kinds | UNVERIFIED: existing pool cases insert admission rows, not Run payloads; fixture identity strings do not prove authorization. |
| No SQL mutation, HTTP mapping, queue, live assessor, scope utility or policy change | Source inspection confirms a mapping-only inactive leaf. Caller search and failed provenance independently establish no runtime consumer; unit passes are not reachable production acceptance. |
| Focused checks, inventory and full required integration CI | Focused checks pass above; provenance fails. Full integration CI remains UNVERIFIED. The frozen failed `test` concerns a different head and has no current-head traceback. |
| Coordinated integration and prerequisites | #1851 types are present and tested. Broader owner coordination, production activation and B1 live migration evidence remain UNVERIFIED/BLOCKED. |

## Final disposition

**BLOCKED.** Only this report changed. No production code, tests, inventory
counts, ledgers, grants or gates changed; no new regression/mutation claim is
made. No inventory delta note is needed without test additions.

Required next input: independently landed, owner-coordinated reachability
authorization followed by authorized base integration, or a separately assigned
real consumer integration. Repairing `test: failure` also requires an attributable
current-head traceback. Neither input is supplied by repeating the same checks.
Do not weaken a gate, invent callers or activate the codec to hide this blocker.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker).
This documentation commit is a blocked handoff, never integration approval.
