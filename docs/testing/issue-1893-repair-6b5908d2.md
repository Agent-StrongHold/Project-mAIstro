# #1893 repair handoff — 6b5908d2

## Frozen scope and decision

One item: #1893, assigned `auto-1893` worktree. Verified starting HEAD
`12c712c7d98c9495c0cf5a68345e1fc30369ebdb`; clean initial tree. Frozen base
`ac7370141e8e61bd6f352bca35ed0b505104aadb` resolves and is the merge base.
Read the supplied dispatch issue body, all five driver check logs, prior result,
codec, immutable identity types and adjacent codec tests. Driver checks pass;
they contain no failing test node or traceback for the supplied `test: failure`.
Assumption: this assignment authorizes evidence-driven repair, not activation.

Read accepted ADRs 081226-a66b, 082526-7f02 and 082826-b601: preserve the
Goal -> Graph -> Run -> NodeRun -> Attempt spine, immutable admission provenance,
and explicit consumer eligibility. No fake import or competing authority is a
valid reachability repair. Legacy pairs without receipt evidence cannot become
`AdmissionBinding` without inventing identity; the typed partial disposition
reconciles the issue's shorthand with its no-inference requirement.

**BLOCKED, not repaired.** The trusted-base gate still rejects the admission
modules and dispositions. The Vulture exception does not authorize reachability
ledger/grant edits. No Vulture discrepancy exists to amend. No conflict or
uncommitted salvage existed, so no develop merge was attempted. No source,
test, ledger, grant, gate, HTTP, queue, assessment or policy changes were made.
Only this handoff is added; test inventory is unchanged, so no delta note is needed.

## Fresh executions

All commands used a 1,200-second timeout. Logs are in
`/home/dev/maistro/jobs/6b5908d2cb8f4af79dfc802e56d031bc/worker-*.log`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1,322 findings, zero unclassified, exact trusted-base identity match.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`:
  FAIL (exit 1). Two NEW unreachable modules absent from the trusted base and
  two NEW unauthorized dispositions: `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec`. Required by `.github/workflows/vulture-ratchet.yml:77`;
  candidate rows are `quality/reachability-baseline.json:131,147` and
  `quality/reachability-dispositions.json:606-613`.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  PASS, **845 passed, 20 PostgreSQL-gated skips**, 865 cases, 16.59 seconds.
  The three raw/production pool contrast cases all skipped, not durability proof.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  PASS, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16,567 collected nodes, zero duplicate evidence.
- Source import search: only the codec imports the identity module; a Vulture
  whitelist imports its enum. No production codec caller found, consistent with
  `admission_codec.py:50-54` and the provenance gate.

## Acceptance accounting

| Criterion | Executed evidence / limit |
| --- | --- |
| Shared frozen/slotted header, six codes, immutable DTOs and flat fresh encoding | Source review plus scoped codec/identity tests passed |
| Named columns, signed scalar timestamps, strict storage UUID .hex, shared constructors | Scalar, owner/generation, identity and schema tests passed |
| Header mismatch/unknown format fail closed | Mismatch and format tests passed |
| Bound/unbound/partial/receipt-only legacy without inferred identity | Binding, missing-receipt, whitespace and completed_at tests passed |
| Header expiry/fingerprint survive full-decode errors | Both separation tests passed; no clock or request fingerprint is accepted |
| Strict TEXT JSON and safe parsing errors | Duplicate/nonobject/nonfinite, nesting, precision-loss, surrogate and scope tests passed |
| Snapshot round trips, evidence tags and unchanged fingerprint | Three in-memory states, explicit SQL binding shape, tagged nonfinite/Unicode/exact-number tests passed |
| Existing evidence-json/model_of/model_of_json materialization and original-model fingerprinting | UNVERIFIED end-to-end: codec fixtures use direct tags, not production materialization |
| Real migrated disposable PostgreSQL raw/production pool contrast | UNVERIFIED this round: required DSNs absent; three skipped cases; no DB session/row counts claimed |
| Run JSONB object and real authorized principals/Workspace/Project/registered Graph | UNVERIFIED: representation tests do not prove admission or canonical Run insertion |
| No mutation/assessment/HTTP/queue/scope-policy changes | Source review and report-only diff; no new authority introduced |
| Production reachability and full unchanged integration CI | Required provenance gate FAILED; full integration CI UNVERIFIED |
| Replacement/409/crash/dispatch invariants | UNVERIFIED and reserved for consumer integration, not B2 |

No pre-fix or mutation failure is claimed because no code defect was repaired.
The generic `test: failure` remains UNRESOLVED, not disproven by scoped passes.
No prior PostgreSQL or full-CI claims were adopted as current execution.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required gate.
Next: owner-controlled trusted-base prerequisite resolution consistent with the
issue's no-activation constraint, plus the actual current failing test traceback.
Then rerun PostgreSQL and integration acceptance. Repeated unchanged scans cannot
supply authorization. This local commit is a blocked handoff, not merge approval.
