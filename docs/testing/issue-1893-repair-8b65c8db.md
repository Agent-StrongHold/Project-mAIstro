# Issue #1893 repair handoff — job 8b65c8db

## Scope and decision

**BLOCKED; no evidence-backed source repair identified.** This round changes only
this report. No tests, inventory counts, production behavior, ledgers, grants or
gates changed. No GitHub mutations, fetch, merge or work disposal occurred.

Frozen assignment: issue #1893, worktree `/home/dev/Git/wt/auto-1893`, clean
starting HEAD `41ca284f985e1c5dd6df8fcdb3542e291b602b36`, dispatched base and
local `origin/develop` `26f86b4634bcf7c4b63394dc5e3dc217308e7e33`.
Editable scope was limited to the existing codec/DTO and adjacent tests for
reproduced defects, the Vulture ledger only for demonstrated reviewed debt,
required inventory notes if tests changed, and this handoff. No conflict was
present, so the conditional develop-conflict repair did not apply.

Read repository instructions, the frozen dispatch issue and linked #1325/#1855
bodies/check evidence, existing implementation/tests, and accepted ADRs
ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Reconciliation: immutable
representation is not execution or authorization; an inactive staged leaf is
not independently mergeable merely because its unit tests pass. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Candidate bookkeeping cannot
supply trusted-base authorization. The Vulture-only exception does not permit
reachability grants, fake callers or consumer activation.

## Executed validation

All executions below used 1200-second tool timeouts at the starting source SHA.
Logs are in `/home/dev/maistro/jobs/8b65c8db38934727b0cd55f72905d41c/`.
The supplied `check-0.log` through `check-4.log` were also inspected; they contain
no failed check, and their focused pytest run skipped three PostgreSQL cases.

| Command | Actual result | Worker log |
| --- | --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1323 reviewed identities, zero unclassified | `worker-vulture.log` |
| `RATCHET_BASE_REV=26f86b4634bcf7c4b63394dc5e3dc217308e7e33 uv run python scripts/check-ratchet-provenance.py` | **Exit 1**; two unauthorized unreachable modules and two unauthorized dispositions | `worker-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: **201 passed, 3 skipped** | `worker-focused.log` |
| `uv run ruff check .` | Exit 0 | `worker-ruff.log` |
| `uv run ruff format --check .` | Exit 0; 3277 files formatted | `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0; two files | `worker-mypy.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0; 16466 nodes, zero copied-file duplicate evidence | `worker-inventory.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0 | `worker-shipped.log` |
| `rg -n 'admission_codec\|admission_identity' packages/*/src` | Only codec-to-DTO and whitelist imports; no production consumer | `worker-callers.log` |

The provenance gate correctly resolves the merge base to `435dc1937e04`, not
the dispatched base's tip. It rejects `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` for both new unreachable identities and new
dispositions absent trusted-base authorization. Existing candidate entries in
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` cannot authorize themselves.
This gate is required at `.github/workflows/vulture-ratchet.yml:77-85`.
The exact Vulture scan found nothing requiring amendment; changing that ledger
would not repair this failure.

## Acceptance audit

Executed tests establish the following **representation contracts**, not live
admission behavior:

- Required frozen/slotted header and interfaces: inspected source; scalar
  validation, mismatch, missing-column and unsupported-format tests pass.
- V2 named, fresh flat mapping and byte-preserving canonical snapshots:
  `test_v2_round_trip_preserves_all_snapshot_bytes` passes in unbound, bound
  and acknowledged states; independent assertions require both binding
  columns and `task_id == receipt_id`. Fresh-mapping test passes.
- Strict UUID hex at storage, signed timestamps and #1851 constructors:
  owner/generation rejection, scalar bounds, constructor/immutability and
  binding identity tests pass.
- Legacy bound/unbound/partial distinction without invented identity:
  `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only,
  missing-receipt, unreadable/whitespace evidence and ignored-completed-at
  cases pass. A bound pair without receipt identity stays a typed partial
  failure because the canonical binding requires that identity.
- Header/full-decode separation: expired-header, preserved-expiry on malformed
  snapshot, preserved-fingerprint on partial binding and header mismatch tests
  pass. Unknown formats cannot become legacy. No clock or incoming request
  fingerprint is accepted; no expiry/claim decision is made.
- TEXT-only strict JSON and safe errors: invalid/duplicate/nonobject/bare
  nonfinite, numeric-loss, Unicode, excessive nesting and predecoded-value
  tests pass. Validated scope and suppressed unsafe chains are asserted.
- Tagged nonfinite evidence and unchanged stored fingerprint: representation
  tests pass for all three tags, exact numbers and Unicode. These hand-built
  fixtures do **not** prove original-model fingerprinting or actual
  `encode_evidence`/`model_of`/`model_of_json` materialization; those remain
  **UNVERIFIED** this round.
- Raw/production pool equivalence on migrated PostgreSQL: **UNVERIFIED**.
  All three cases skip at `test_admission_codec.py:470` for missing DSNs.
  No disposable database was provisioned; no database session identities,
  migration-chain/downgrade, SQL row/identity counts or durability proof are
  claimed. Run JSONB object insertion is also **UNVERIFIED**; these tests
  insert only admission rows.
- Explicit authorized principals, Workspace/Project and registered Graph
  kinds: **UNVERIFIED**. Fixture strings do not prove authorization.
- No SQL mutation, HTTP/queue/assessor/scope-utility/policy changes: inspected
  codec remains mapping-only and this round changes documentation only.
  Production reachability is absent, independently corroborated by the gate
  and caller search. Expired replacement and mismatch-409 precedence remain
  **UNVERIFIED**, owned by C/F2, not implemented by B2.
- Focused tests, lint, format, types and inventory pass as above. No new test
  means no inventory delta note is needed. No new pre-fix/mutation experiment
  is claimed. Full unchanged integration CI remains **UNVERIFIED** and the
  required provenance gate is **FAILED**.
- Repair ownership comes from the lane assignment; broader stack coordination
  and activation remain **UNVERIFIED/BLOCKED**, not implied by that ownership.

## Test-failure attribution and next action

The frozen dispatch contains a failed `test` check for #1855 at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with no summary or traceback.
The captured #1945 `test` check succeeds at
`9922f395daa39249991f18210a6d4da68a3a76cb`. Neither is this assigned head.
Extracted evidence is `worker-captured-tests.json`. The generic current-head
`test: failure` attribution is **UNRESOLVED**. The CI `test` job at
`.github/workflows/ci.yml:496` spans other packages/root suites; a focused core
pass is not a reproduction of that job. No speculative test or scanner fix
was made.

Required next inputs: independently landed owner-coordinated reachability
authorization followed by authorized integration-base sync, or separately
assigned real consumer integration; and a current-head failing CI traceback
for any test repair. Do not dispatch another unchanged-source validation round
as a substitute for those inputs.

Progress: checked 1, done 0, skipped 0, errors 1 reproduced provenance blocker.
Local documentation commit is a handoff only, not integration approval.
