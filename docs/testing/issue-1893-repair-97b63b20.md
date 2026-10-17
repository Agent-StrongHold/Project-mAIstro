# Issue #1893 repair checkpoint — 97b63b20

## Frozen scope

- Sole issue: #1893; assigned worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `b0e603d4da3e2b6a80006cfbb93b2d8a7523e0c3` (verified, clean).
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved).
- Inspect existing admission codec, immutable identity types, adjacent tests,
  relevant ADRs and CI gates. Only evidence-supported repairs are permitted.
- Candidate edit files: this report; codec/identity and their existing test files
  only if a regression is reproduced; inventory note if tests change; Vulture
  ledger only if the instructed exact scan establishes retained unbanked debt.
- No remote mutation, activation, competing execution authority or reachability
  grant/ledger edits. No develop-sync conflict exists at entry.

## Initial evidence and ambiguity

Read the supplied dispatch snapshot and prior result artifact. Driver logs
`check-0.log` through `check-4.log` show dependency sync, ruff, format and inventory
passing; focused tests report 201 passed and 3 skipped. These are driver results,
not live PostgreSQL proof. Prior result remains BLOCKED on trusted-base
reachability provenance. The generic `test: failure` has no failing node/traceback
in the supplied check logs. Assumption: reproduce relevant local tests/gates;
do not guess a source fix or change unrelated tests.

## Reproduced blocker

The exact instructed Vulture scan passed (1323 findings, 1323 reviewed identities,
zero unclassified). No Vulture ledger amendment is warranted. The workflow's
trusted-base gate failed against the supplied resolved base: both admission
modules have new unauthorized unreachable-module entries and dispositions
(169 trusted modules versus 171 candidate modules). Logs: `worker-vulture.log`
and `worker-provenance.log` in the job directory. This is an actual policy
failure, not a missing dependency.

Read accepted ADR-081426-1f7c and ADR-082526-7f02. Attempt-owned execution and
immutable admission provenance remain authoritative. Production-source search
finds the codec importing the DTO and a whitelist importing the DTO, but no
runtime codec consumer. The module explicitly documents that deferred consumer
at `admission_codec.py:51-54`. Adding a fake caller or activating the future
consumer would violate this leaf's scope. A Vulture-only repair exception does
not authorize reachability grant or ledger changes. The previous block remains
unresolved; do not repeat the failed gate hoping for a different result.

## Executed validation

All commands ran in the assigned worktree against the starting source SHA;
validation subprocesses used 1200-second timeouts. Logs are retained in
`/home/dev/maistro/jobs/97b63b2022974a5ea64692dc30b334b3`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 reviewed identities / findings; `worker-vulture.log`. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1; two unauthorized modules and two dispositions; `worker-provenance.log`. Required by `.github/workflows/vulture-ratchet.yml:77`. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q --junitxml=/home/dev/maistro/jobs/97b63b2022974a5ea64692dc30b334b3/worker-focused.xml` | 204 collected; 201 passed, 3 skipped in 1.25s. Three existing record_property/xunit2 warnings. Node IDs and outcomes in XML; `worker-focused.log`. |
| `uv run ruff check .` | PASS; `worker-ruff.log`. |
| `uv run ruff format --check .` | PASS, 3277 files; `worker-format.log`. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two source files; `worker-mypy.log`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicates; `worker-inventory.log`. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `worker-check-shipped-surface-truth.py.log`. |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger, 1396 modules / 171 unreachable; `worker-check-reachability.py.log`. |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger, 50 groups / 171 modules; `worker-check-reachability-dispositions.py.log`. |
| `uv run python scripts/check-promotion-surface.py` | PASS; `worker-check-promotion-surface.py.log`. |

Candidate-ledger consistency does not override the failed trusted-base check.
Existing problematic rows remain at `quality/reachability-baseline.json:131,147`
and `quality/reachability-dispositions.json:612-613`; they were not changed.
Read the captured #1325 and #1855 PR bodies/heads from the supplied snapshot;
neither their historical check claims nor issue comments substitute for this
head's validation. No remote refresh or integration operation was performed.

## Acceptance audit

Reviewed codec, immutable DTO implementation and both complete focused test
files. The following distinguishes executed leaf contracts from production
behavior. No new tests were added, so no inventory delta note is needed.

| Criterion | Current evidence / limit |
| --- | --- |
| Exact shared interfaces; frozen/slotted scalar header; named SQL columns | Source inspection plus passing header/scalar mismatch and mapping tests. Header immutability is structural (`@dataclass(frozen=True, slots=True)`). |
| Strict lowercase storage UUID hex, signed timestamps, #1851 constructors | Passing owner-token, generation, scalar rejection and DTO constructor tests. |
| V2 fresh flat mapping and all snapshot bytes, binding and acknowledgement | Three state-parametrized unit round trips pass. Independent binding-column assertions pin migration-055 shape. Not fresh database proof. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run | Passing legacy binding and partial-evidence tests. Reconciliation: #1851 AdmissionBinding requires a receipt; paired task/run evidence without a receipt remains partial rather than inventing identity. |
| Expired legacy header preserves facts without inventing identity | Named header tests pass; no clock is read. Expiry decisions remain outside this leaf. |
| Header preserves expiry with malformed snapshots and fingerprint with partial binding | Both named separation tests pass; full decode errors leave header evidence intact. |
| Unknown formats, invalid scalar headers and header/row mismatch fail closed | Passing parameterized rejection tests; no reinterpretation as legacy. |
| Strict TEXT snapshots; duplicate/nonobject/bare nonfinite rejection | Passing JSON, predecoded-value, overflow, nesting, numeric-fidelity and Unicode rejection tests. |
| Six typed error codes; validated scope only; no raw snapshot/owner-token or exposed parsing chain | Source inspection and passing error-hygiene tests with injected malformed storage values. No new web serialization. |
| Tagged nonfinite program_context and unchanged stored fingerprint | Passing nan/inf/-inf preservation tests. Tags and fingerprint are fixture values, not evidence of original-model fingerprint computation. |
| Actual evidence-json encoding and model_of/model_of_json materialization | UNVERIFIED in this round; codec deliberately preserves tags rather than materializing models. Fixtures do not prove the future consumer's model path. |
| Raw and production JSON-codec pools against the same real migrated disposable PostgreSQL DB | UNVERIFIED: all three PG legs skipped for missing configuration. No DB session IDs or final SQL counts obtained. Prior-run PostgreSQL claims are not adopted as this run's proof. |
| Run payload INSERT is text-to-JSONB and stores an object, not a JSON string | UNVERIFIED: focused tests do not create canonical Runs. |
| Real explicit principals, authorized Workspace/Project and registered Graph kinds | UNVERIFIED: direct codec fixtures use placeholder identities, not the authorized admission path. |
| No SQL mutation, queue/HTTP/assessor/scope change, expiry/mismatch classification or authorization authority | Source inspection: codec only reads/returns mappings. This round edits only this report; canonical Goal -> Graph -> Run -> NodeRun -> Attempt is unchanged. |
| Focused pytest, ruff, format, mypy and truthful inventory | Executed results above; no test additions/deletions or inventory edits. No new pre-fix/mutation claim. |
| Required CI, runtime reachability and independently mergeable staging | BLOCKED: trusted-base provenance fails; no runtime consumer exists. Full required CI and the unspecified `test: failure` remain UNVERIFIED, not repaired. |
| Coordinated ownership/base and activation restrictions | Assigned worktree/base honored. No production activation, policy selection, merge approval or issue closure. |

## Handoff

**BLOCKED.** No evidence-backed source or Vulture ledger repair was found. Only
this report changed and is committed locally. The owner must provide an
already-landed trusted-base prerequisite or separately authorized consumer
integration; this worker cannot manufacture either. Supply the actual failing
CI test command/node/traceback before another test-repair round. A new
reachability grant in this candidate would not authorize itself, and is outside
this lane's permitted edits.

Progress: checked 1 issue; done 0 source repairs; skipped 0 issues; errors 1
unresolved required gate. Next: owner coordination for the trusted-base blocker.

