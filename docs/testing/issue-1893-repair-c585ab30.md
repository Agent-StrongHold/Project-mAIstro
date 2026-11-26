# Issue #1893 repair checkpoint — c585ab30

## Frozen scope

- Assignment: #1893 only, branch `auto-1893`.
- Starting HEAD: `d82de454df93cebaafd93009167d6dcc39573eea` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree clean; no incoming edits to salvage.
- Inspect only admission codec/identity modules, their adjacent tests, relevant ADRs,
  CI workflows/gates, supplied dispatch evidence and prior result. No GitHub mutations.
- Candidate change: this report; production/test repairs only if reproduced evidence
  identifies an in-scope defect. No reachability grants/ledger changes authorized.

## Initial evidence

Driver `check-0.log` reports dependency sync success; `check-1.log` lint passed;
`check-2.log` 3277 files formatted; `check-3.log` 201 passed, 3 skipped;
`check-4.log` suite inventory passed (16466 core nodes). These are driver results,
not new execution or PostgreSQL durability evidence.

Ambiguity: dispatch names only `test: failure`, without a failing node. Assume a
focused reproduction plus inspection of captured CI evidence is required, not a
speculative test or ledger change. Prior reachability provenance blocker must be
reproduced before any readiness claim.

## Reproduced gate result

The supplied base resolves and is the actual merge base; no sync conflict exists.
Executed `uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed identities,
zero unclassified. No Vulture ledger amendment is justified.

Executed `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run
python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new
unauthorized unreachable modules and dispositions (169 trusted, 171 candidate).
This is not a dependency error. The Vulture-only exception cannot authorize
reachability ledger/grant changes, and artificial imports would violate scope.

## Focused validation (fresh worker execution)

All commands used 1200-second tool timeouts on the unchanged starting source.

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | 204 nodes: 201 passed, 3 skipped in 1.44s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, zero duplicate evidence |

PostgreSQL skips explicitly require both DSNs at
`test_admission_codec.py:470`. No database durability proof, session IDs or SQL
residue counts are claimed this round. No tests added/removed; no inventory
note delta is necessary.

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Reconciliation:
keep canonical execution authority and immutable admission provenance; do not
let candidate evidence authorize itself. This repair cannot resolve a
trusted-base governance blocker by activation or self-approval.

Additional executed gates: `uv run python scripts/check-shipped-surface-truth.py`,
`uv run python scripts/check-reachability.py`, `uv run python
scripts/check-reachability-dispositions.py`, and `uv run python
scripts/check-promotion-surface.py` all PASS. Candidate reachability bookkeeping
reports 171 unreachable modules and 50 disposition groups; passing candidate
bookkeeping does not override the failed trusted-base provenance check.

## Acceptance review

All test evidence below is from the fresh 204-node focused run, not an assertion
of reachable admission behavior. Production import search finds only the codec
importing the DTO and a Vulture whitelist import; `PgTaskIdempotencyStore._read`
at `packages/maistro-core/src/maistro/tasks/idempotency.py:1180-1191` still calls
the old `_row_of`, not the new codec.

| Criterion | Evidence / limitation |
| --- | --- |
| Exact interfaces, frozen/slotted header, six typed decode codes | Inspected `admission_codec.py:129-262`; header, schema and mismatch tests PASS. |
| Named columns, strict UUID .hex, signed timestamps, #1851 constructors | Strict UUID, scalar/window, owner-token tests PASS; source validates by column name. |
| Fresh flat mapping and immutable snapshot round trip | Three state round trips and fresh mapping tests PASS; independent task/run SQL shape assertions at `test_admission_codec.py:134-137`. |
| Legacy both/neither/partial, receipt-only, announced-without-Run | Legacy tests PASS; both IDs without receipt remain partial because the binding DTO requires a receipt. No receipt is synthesized. |
| Header survives malformed snapshot/partial binding, unknown formats fail closed | Named expiry/fingerprint preservation and unknown-format tests PASS. Header decoder takes no clock or incoming fingerprint. Replacement/409 precedence belongs to consumer C, not this leaf. |
| Strict TEXT JSON rejects duplicate keys, nonobjects and bare nonfinite tokens | Invalid JSON tests PASS; direct stored-TEXT nesting, lossy numeric and surrogate injections also PASS, with exact-number/Unicode positive cases. No new pre-fix/mutation experiment claimed. |
| Safe typed errors and validated scope hash | Error-scope, token hygiene and snapshot error tests PASS; displayed parsing chains suppressed. |
| Tagged evidence and unchanged fingerprint | Tag round trips PASS; codec does not decode tags or recompute fingerprint. Actual evidence-json producer plus TaskCreate/TaskResponse/Run model materialization remains UNVERIFIED: fixtures construct tag dictionaries. |
| Physical SQL mapping | Source encodes DTO request_snapshot into existing `request` TEXT and owner_token into `claim_token`; binding writes both task_id and run_id. Live migrated schema execution UNVERIFIED this round. |
| Same disposable migrated DB, raw/production pools, non-null pg_pool | UNVERIFIED: three tests skipped for absent DSNs. No database provisioned after independent governance blocker reproduced. |
| Run INSERT text-to-jsonb and object payload, real authorized principals/Workspace/Project/registered Graph kinds | UNVERIFIED by this codec run; fixture identity strings are not authorization or Run durability proof. |
| No SQL mutation, HTTP/queue policy, live assessor, scope utility, clock or decision change | Source inspection PASS for staged codec; this round changes only this report. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt preserved. |
| Focused tests, lint, formatting, typing, inventory and required integration CI | Focused checks PASS above. Full integration CI UNVERIFIED; mandatory trusted-base provenance FAIL. No tests changed, no inventory delta required. |

## Reported test failure

Parsed the four captured `test` check records in the supplied dispatch JSON.
Only head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` reports failure, with null
summary/text; the other three are successful. None names this assignment's
starting HEAD. No assigned-head failing node/traceback is supplied.
**UNRESOLVED:** focused tests pass but cannot establish the CI `test` job,
which partitions core tests into another producer (`.github/workflows/ci.yml:574`).
A speculative code/ledger change is not an evidence-backed repair.

## Handoff

Verdict: **BLOCKED**. Only changed file:
`docs/testing/issue-1893-repair-c585ab30.md`. No production, tests, whitelist,
quality ledger, grant or gate changes. No GitHub mutation, merge, activation or
work deletion. Existing implementation preserved; locally commit this report.

Next: obtain independently authorized trusted-base reachability resolution (or
separately authorized real consumer integration) and the assigned-head failing
CI step/node/traceback. Do not repeat this unchanged-base Vulture repair:
Vulture passes and cannot authorize reachability. Revalidate DB/materialization
and full integration acceptance after the blocker is resolved.

Progress: checked 1, done 0, skipped 0, errors 1 (required provenance gate).
Residual risks: inactive codec, unproven live DB/materialization/authorization
acceptance, and missing assigned-head CI failure evidence.
