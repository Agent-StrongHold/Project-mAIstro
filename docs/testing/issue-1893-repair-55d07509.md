# Issue #1893 repair checkpoint (55d07509)

## Frozen scope

- One item: issue #1893, branch `auto-1893`, assigned worktree
  `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `7f10f4fb188e53b08ff0458d46411051346865db` (verified;
  initial working tree clean). Frozen develop base:
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Process only the supplied dispatch snapshot; no GitHub mutations or new issue
  enumeration. Related PRs are context, not additional repair assignments.
- Review scope: admission codec, admission identity types, adjacent tests,
  applicable ADRs, workflow gates and existing quality records. Intended write
  scope: this report; codec/tests only if a defect reproduces; vulture ledger
  only if the mandated scan identifies reviewed retained debt. Reachability
  grants/ledgers and activation are not authorized changes.

## Initial evidence / ambiguity

The supplied driver logs report ruff and format passing; focused tests report
346 passed / 3 skipped; core inventory reports 16,567 nodes. These are driver
claims, not this worker's executions. The supplied `test: failure` has no failing
node or traceback in those logs. Assumption: independently rerun the codec and
identity tests plus applicable gates; do not invent a test repair. The earlier
reachability authorization blocker must be rechecked against the frozen base.
No conflict or uncommitted work exists at the starting head, so no develop merge
or salvage operation is warranted.

## Executed checkpoint

The frozen base resolves to a commit and is the merge base with HEAD.
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence
60 --exclude '*/third_party/*'` passed: 1,322 findings, zero unclassified.
No vulture ledger amendment is justified.

`RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python
scripts/check-ratchet-provenance.py` exited 1. Both
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are NEW
unreachable modules without trusted-base authorization; both candidate
reachability dispositions also lack authorization. This reproduces the prior
blocker, rather than a develop-sync conflict. Candidate-side grants, fake
callers, exports, and activation are not permissible repairs.

`uv run pytest packages/maistro-core/tests/tasks
packages/maistro-core/tests/runs/test_root_admission_identity.py
packages/maistro-core/tests/extensions/test_cli_lock.py
packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
**845 passed, 20 skipped**, 865 collected cases, 16.44s. Every skip is
PostgreSQL-environment gated, including all three codec pool contrasts.
These skips are not durability evidence.

`uv run ruff check .` and `uv run ruff format --check .`: PASS (3,301 files).
`uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
Commands used 1,000–1,200-second timeouts.

Source import search found only codec-to-DTO and whitelist imports, not a
production consumer. This agrees with the module's explicit inactive boundary
and the failed provenance gate.

Additional executed gates (1,200-second timeout):

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16,567 collected nodes, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger,
  1,403 production modules / 171 unreachable. This does not authorize new debt.
- `uv run python scripts/check-reachability-dispositions.py`: PASS against
  candidate ledger, 50 groups / 171 modules. Provenance still fails.
- `uv run python scripts/check-promotion-surface.py`: PASS, 74 tolerated modules.

## Architecture and acceptance review

Read repository instructions, the supplied issue body and PR review evidence,
prior result (not adopted as fresh execution), codec and identity implementation,
adjacent tests and accepted ADRs 081226-a66b, 082526-7f02 and 082826-b601.
Those ADRs preserve the one Run/NodeRun/Attempt lifecycle, immutable admission
provenance and explicit consumer eligibility. No alternate scheduler, authority,
store, authorization path or fake consumer is a legitimate repair here.
The issue's legacy bound-pair wording cannot require inventing a missing receipt:
`AdmissionBinding` requires receipt identity, so a pair without that evidence
remains an explicit partial failure, as tested.

| Criterion | Fresh evidence or explicit limit |
| --- | --- |
| Exact shared interfaces, frozen/slotted header and six codes | Source review of `admission_codec.py`; header/schema/scalar tests passed in the command above |
| Named columns, signed timestamps, strict UUID .hex and shared constructors | Owner/generation/scalar/identity tests passed; no positional SQL-row decoding |
| Flat fresh mapping and immutable snapshot round trips | Three in-memory states and independent task_id/run_id/acknowledged_at assertions passed (`test_admission_codec.py:130-154`) |
| Header mismatch and unsupported format fail closed | Scalar mismatch, missing-column and unknown-format tests passed |
| Bound, unresolved, partial and receipt-only legacy without identity inference | Binding, missing receipt, whitespace and completed_at tests passed |
| Header expiry/fingerprint survive full-decode errors | Both separation tests passed; source has no clock, incoming fingerprint or claim decision |
| Strict TEXT JSON and safe errors | Duplicate/nonobject/nonfinite, nesting, lossy-number, Unicode and validated-scope tests passed; parsing chains suppressed |
| Permitted tagged program_context and unchanged fingerprint | Tag/Unicode/exact-number tests passed; source never recalculates fingerprint or decodes tags |
| Existing evidence-json/model_of/model_of_json integration and original-model fingerprinting | UNVERIFIED end-to-end: fixtures construct tags directly; no model materialization in this leaf |
| Raw/production pool contrast on one migrated disposable DB | UNVERIFIED this round: all three real DB tests skipped for absent environment; earlier PG claims not adopted |
| Run payload text::jsonb is an object, not double-encoded | UNVERIFIED: no canonical Run insertion exercised by this round |
| Real principals, authorized Workspace/Project and registered Graph kinds | UNVERIFIED as admission: DTO identity strings are not authorization evidence |
| Production reachability and unchanged full integration CI | FAILED prerequisite: provenance gate rejects both new unreachable modules and dispositions; full CI not run |
| Inclusive-expiry/replacement/409, crash, dispatch or claim invariants | UNVERIFIED and explicitly reserved for C/F2, not B2 representation behavior |
| No SQL mutation, HTTP/queue/scope/assessor or policy changes | Preserved; this round changes only this report |

No new tests or test-count changes: no inventory delta or inventory-note update
is needed. No source repair or pre-fix/mutation failure is claimed. The generic
`test: failure` remains UNRESOLVED: supplied driver logs contain no failing node,
and this worker's scoped test command passes. Passing focused tests does not
prove the entire CI job is repaired.

## Final handoff

**BLOCKED.** The actual reproduced failure is trusted-base authorization at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`, required by
`.github/workflows/vulture-ratchet.yml:77`. Preserve the existing work; do not
change ledgers/grants/gates or activate this slice to manufacture green CI.
The allowed Vulture repair exception cannot authorize reachability debt, and
its scan found no discrepancy to amend.

Changed file: this report only. No source, test, ledger or grant edits; no
fetch, merge, push, PR/issue mutation, or destructive Git operation. Local
commit is an evidence handoff, not integration approval.

Progress: checked 1, done 0 code repairs, skipped 0 issues, errors 1 required
gate. Next: owner-controlled trusted-base prerequisite resolution; provide a
current-head failing test traceback for any separate test repair, then rerun
real PostgreSQL and integration acceptance. Repeated scans of unchanged code
cannot resolve the owner-controlled prerequisite.
