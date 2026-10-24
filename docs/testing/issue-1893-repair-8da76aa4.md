# Issue #1893 repair — 8da76aa4

## Frozen scope

- Assigned writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head `dc5c64da6786ea67abbd5d2c5328875976eea85b`; supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`. Both resolve locally. Initial worktree clean; no salvage required.
- Process only #1893, supplied dispatch snapshot and check-0.log through check-4.log. No GitHub mutations or list refresh.
- Inspection scope: repository instructions/ADRs, admission codec/identity modules and adjacent tests, CI test/quality commands, existing #1893 notes, named quality ledgers. Edit scope: evidence-driven admission repair if found, required inventory note if tests added, this validation report. Vulture ledger amendment only if the prescribed scan establishes reviewed retained debt; no reachability ledger/grant changes.
- Ambiguity: generic `test: failure` has no failing node in the assignment. Treat supplied logs as evidence, not permission for speculative code changes. Prior verification claims must be rechecked.
- Staged typed representation only; production activation and integration ownership remain outside this repair.

## Progress

1. Confirmed exact starting head and clean worktree; read full issue body from the frozen dispatch.
2. Inspected all five driver logs: sync, ruff, format and suite inventory pass; focused tests report 201 passed / 3 skipped. No failing test traceback is supplied. Read prior result and report as historical evidence only.
3. Independently executed the prescribed Vulture scan (1200-second timeout): PASS, 1323 reviewed findings, zero unclassified. No Vulture ledger amendment is justified.
4. Independently executed `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` (1200-second timeout): FAIL, exit 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are unauthorized new unreachable modules and new dispositions (trusted 169, candidate 171). This reproduces the earlier external blocker; it is not a Vulture discrepancy. The workflow requires this command at `.github/workflows/vulture-ratchet.yml:77`. No reachability/grant modifications are permitted in this lane.

## Architecture and acceptance review

Read repository instructions, documentation authority map, accepted ADR-082526-7f02 and ADR-081426-1f7c, complete codec/identity implementations and both adjacent test files. Admission provenance stays immutable; physical execution identity belongs to Attempt. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing scheduler/store/authorization is introduced.

Read frozen PR #1325, #1855 and #1945 descriptions with their own captured head qualifiers; none constitutes current validation or activation authorization. The supplied develop base is already this head's merge base, as independently confirmed by `git merge-base`; no develop-sync conflict exists at the assigned snapshot.

Legacy reconciliation: the issue's shorthand that a task/run pair is bound cannot justify fabricating the receipt required by #1851's binding constructor. A pair without receipt evidence remains a typed partial failure, as the stronger no-invented-identity constraint requires.

| Criterion | Current evidence / limitation |
| --- | --- |
| Exact shared interfaces, frozen/slotted header, six failure codes | Source review; focused schema/header tests pass |
| Named columns, strict UUID .hex, signed timestamps, #1851 constructors | Focused owner/generation/scalar/constructor tests pass |
| V2 snapshots, fresh flat SQL mapping and binding identity | Unbound/bound/acknowledged in-memory round trips pass; independent task_id = receipt_id and paired-column assertions pass |
| Legacy bound/unbound/partial, receipt-only, announced-without-Run | Focused legacy tests pass; no invented identity, completed_at grants no authority |
| Header retains expiry/fingerprint despite snapshot/binding errors; supplied header must match row | Named header preservation/mismatch tests pass |
| Unsupported schema/format and invalid scalar fail closed | Focused schema/format/scalar tests pass |
| TEXT JSON rejects duplicate/nonobject/bare nonfinite, numeric loss, excessive nesting and lone surrogates | Focused snapshot boundary tests pass; safe typed errors and suppressed chains asserted |
| Tagged nonfinite program_context and unchanged stored fingerprint | Focused tagged/numeric/Unicode tests pass at representation boundary; no recomputation or tag decoding in codec |
| No clock, incoming fingerprint, assessment, claim mutation, SQL mutation, HTTP/queue/policy change | Complete codec source review; no source changes this round |
| Raw and production pools against same migrated disposable PostgreSQL | UNVERIFIED this round: three tests skip for missing required DSN variables; no DB mutated and no session or row-count proof claimed |
| Existing evidence-json encoder and model_of/model_of_json materialization; original-model fingerprint | UNVERIFIED: fixture dictionaries test stored tags, not production model persistence |
| Run payload JSONB is an object; explicit principals, authorized Workspace/Project, registered Graph kinds | UNVERIFIED: no Run persistence or authorization path executed; DTO fixture strings are not authorization proof |
| Inclusive expiry/replacement and changed-payload 409 precedence | UNVERIFIED, explicitly C/F2 consumer behavior rather than B2 |
| Reachable production behavior | NOT ESTABLISHED: source import search finds only codec-to-identity and whitelist import; no production codec consumer; required provenance fails |
| Common focused validation and truthful inventory | Fresh results below; no tests added, inventory delta zero, no new mutation/pre-fix claim |
| Full required CI / reported test failure | UNVERIFIED: focused tests pass, required provenance fails; supplied logs contain no failing test traceback |
| Coordination / activation / independent integration readiness | BLOCKED: external ownership/policy and trusted-base reachability prerequisites are not resolved by this lane |

## Fresh validation

Executed against starting source `dc5c64da6786ea67abbd5d2c5328875976eea85b`, with 1200-second timeout for validation commands:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323 reviewed findings, zero unclassified |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL exit 1; two unauthorized unreachable modules and two dispositions |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; two source files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes; 201 passed, 3 skipped in 1.27s |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 16466 nodes, zero duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

An initial glob-filtered import search returned no matches and was not used as reachability evidence. The corrected search over `packages/*/src` finds `admission_codec.py:67` importing the identity DTOs and `_vulture_whitelist.py:105` importing AdmissionAssessment, and no production codec consumer. This independently agrees with the failing reachability gate.

## Handoff

Changed file: this report only. No reproducible in-scope code defect or Vulture ledger discrepancy was found. No source/test/ledger/gate changes, no inventory delta, no DB mutation, and no GitHub mutation.

The blocking entries remain `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. An owner-approved authorization must land on the trusted base first under the two-merge rule, or a separately authorized runtime integration must resolve reachability. This Vulture-only repair exception cannot authorize either action. Re-running this lane against the same base cannot repair that prerequisite. For the generic `test: failure`, supply the failing command/node/traceback at the current head before requesting code repair.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1 required provenance gate; next: external trusted-base prerequisite and concrete failing-test evidence. Verdict **BLOCKED**. Commit this evidence handoff locally; it is not integration approval or issue closeout.
