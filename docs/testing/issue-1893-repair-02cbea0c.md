# Issue #1893 repair checkpoint (job 02cbea0c)

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893` in the assigned worktree.
- Starting source: `bf502d45edf810b35eea6adf984ae1c92505651a` (clean).
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect existing `admission_codec.py`, `admission_identity.py`, their two test
  files, governing ADRs, and the exact CI gate configuration. No other issue or
  PR is being processed. This report is the only planned edit unless a failure
  establishes a scoped code repair; no tests or inventory counts changed yet.
- Driver logs `check-0.log` through `check-4.log` inspected: dependency sync,
  lint, formatting and inventory succeeded; focused tests: 201 passed,
  3 skipped. These are driver evidence, not independent validation.

## Ambiguity and boundaries

The supplied `test: failure` has no traceback in the driver logs. The prior
result reports a separate provenance blocker. Independently reproduce the named
checks rather than infer dead code or change a ledger speculatively. Permission
to amend the Vulture ledger does not authorize reachability ledger/grant edits
or production activation. No develop-sync conflict is present, so no speculative
merge is planned. Staged codec readiness is not rollout or integration approval.

## Independent validation checkpoint

Executed against unchanged starting Python source (1200-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: pass, 1323 findings, zero unclassified. No ledger amendment justified.
- Verified the supplied base resolves, then ran `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL, two unauthorized new unreachable modules and two unauthorized dispositions (`maistro.runs.admission_identity`, `maistro.tasks.admission_codec`). All other subgates pass. This is a reachability authority blocker, not Vulture debt.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s`: 201 passed, 3 skipped (both PostgreSQL DSNs required at test_admission_codec.py:470). No live DB proof claimed.

No implementation edit is warranted by those results. Do not self-authorize the inactive modules.

Additional independent commands (1200-second timeout), all passing:

- `uv run ruff check .`
- `uv run ruff format --check .` (3277 files)
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` (2 files)
- `uv run python scripts/check-shipped-surface-truth.py`
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` (16466 nodes, zero duplicate evidence)

A source-reference search across `packages/*/src` finds only the codec's import
of identity types and the Vulture whitelist import; no production consumer.
The supplied dispatch snapshot's failed `test` check is on dependency head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the assigned head, and has null
output title/summary/text. Its `exact-debt-ledger` failure names
`fcc8b437f209a35aa68a61d6f0a5387414938355`. No assigned-head test traceback was
provided. The CI `test` job explicitly excludes core (`ci.yml:574` onward), so
these focused passes are not evidence that the reported CI job was repaired.

## Acceptance audit

Read repository instructions, documentation authority hierarchy and accepted
ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt model, immutable admission provenance,
Attempt-owned dispatch identity and trusted-base authorization. None authorizes
self-approval of an inactive slice. Inspected both implementation modules, both
focused test files, migration 055's storage/CHECK contract and references to the
separate live idempotency assessor.

All 204 focused nodes collected; 201 executed, 3 skipped. No new tests or
inventory-count changes; no inventory-delta note required for this report.

| Criterion | Current evidence / limit |
| --- | --- |
| Frozen/slotted header, exact signatures and six typed decode codes | Source inspected; header/scalar and DTO tests pass. |
| Named columns, signed timestamps, strict storage UUID .hex and #1851 constructors | Schema, UUID, scalar mismatch and constructor cases pass; fresh flat mapping test passes. |
| Safe errors and validated-hash scope only | Negative snapshot, invalid scope, owner-token and suppressed-chain assertions pass; raw inputs are not in error messages. |
| Immutable v2 snapshots and unchanged stored fingerprint | Unbound/bound/acknowledged round trips and tagged nonfinite tests pass. Fixtures supply tags and fingerprints; original-model fingerprinting and model_of/model_of_json materialization remain UNVERIFIED. |
| Strict TEXT JSON and arbitrary permitted evidence | Duplicate/nonobject/nonfinite/overflow, lossy numeric, deep nesting and surrogate rejection cases pass; valid Unicode and exact-number normalization pass. Codec does not decode tags twice. |
| Legacy bound/unbound/partial/receipt-only dispositions without inferred identity | Focused cases pass. A pair without receipt evidence remains partial because the canonical binding requires receipt identity: no-invention takes precedence over the issue's shorthand that both IDs are bound. |
| Scalar header survives full snapshot/binding failure; unsupported format fails closed | Both named header-separation tests and unknown-format cases pass. No clock/incoming fingerprint argument or claim decision is introduced. |
| SQL field mapping, binding and acknowledgement | Migration 055 inspected: physical request TEXT maps to request_snapshot; paired task_id/run_id with task_id=receipt_id. Independent encoder shape assertion and mismatched-receipt test pass. Optional completed_at grants no authority. |
| Migrated disposable PostgreSQL, matching DSNs, raw/production codec pools and session/row counts | UNVERIFIED this round: all three DB cases skipped for missing DSNs. No live migration or durability result claimed. |
| Run INSERT JSONB object, real explicit authorized principals/Workspace/Project/registered Graph | UNVERIFIED: pure codec fixtures are identity strings, not authorized runtime admissions; no Run INSERT executed. |
| No SQL/HTTP/queue mutation, scope utility, classifier, claim or policy change | Codec is mapping-to-DTO only; existing live assessor is separate. This repair changes only this report. Consumer expiry/replacement/409 precedence is outside B2 and UNVERIFIED. |
| Meaningful regression evidence and inventory | Existing negative tests inject raw storage values rather than pre-normalized DTOs; all execute. No new mutation/pre-fix experiment claimed; inventory gate passes unchanged. |
| Required integration CI and production reachability | NOT proven: trusted-base gate fails with four findings; no production consumer. Full integration CI UNVERIFIED. |
| Coordinated base/ownership and activation | Assigned repair work only. External stack coordination UNVERIFIED; no activation, integration approval, policy choice or parent closeout authorized. |

## Final handoff

BLOCKED. Only `docs/testing/issue-1893-repair-02cbea0c.md` changed. No code,
tests, ledgers, grants or gates changed; no GitHub mutation. Vulture passes, so
its CI-repair exception supplies no repair for the actual reachability failure.

Blocking evidence: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` are rejected by the trusted-base
check required at `.github/workflows/vulture-ratchet.yml:77`. Resolving this
requires separately authorized trusted-base work or consumer integration;
neither is allowed by this leaf. Obtain an assigned-head failing test step and
traceback before attempting a test-specific repair. Repeating the unchanged
dispatch cannot resolve the authority blocker.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required gate.
Next: owner decision on authorized integration/provenance, plus concrete test
failure evidence. Residual risks are inactive production behavior and unverified
live DB, model materialization, authorization and full integration CI. Commit
this report locally as a blocked handoff, not merge or rollout approval.
