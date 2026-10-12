# Issue #1893 repair checkpoint — 6175e98a

## Frozen scope

- Assigned item: #1893 only; writer on `auto-1893` in `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `3784aba38c73368dd621cdc74a9de3460a50f39a`; supplied develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree clean. No incoming edits to salvage.
- Inspection scope: supplied dispatch snapshot and check logs; repository instructions, relevant ADRs, codec/identity modules and their two test files, CI gate definitions and existing admission inventory notes.
- Candidate edit scope: those codec/identity modules and tests only if a concrete regression is reproduced; associated inventory note if tests change; this evidence report. No reachability/grant/gate edits. Vulture ledger changes permitted only for reproduced retained identities per assignment.
- Single item remains in validation. No remote mutation, activation, or ownership change authorized.

## Initial evidence and ambiguity

Read supplied `check-0.log` through `check-4.log`: dependency sync, Ruff and formatting pass; focused tests report 201 passed / 3 skipped; suite inventory passes (16466 nodes). These are driver results, not newly executed validation or PostgreSQL evidence.

The prior job result reports a trusted-base reachability provenance failure and no assigned-head traceback for the generic `test: failure`. Assumption: re-run the exact named gate and focused validation before deciding whether any code/ledger repair is justified. Do not invent findings or authorize reachability debt locally.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 retained identities, zero unclassified. No ledger amendment justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Two new unreachable modules (`maistro.runs.admission_identity`, `maistro.tasks.admission_codec`) and their dispositions have no trusted-base authorization (169 base, 171 candidate).
- Verified `origin/develop` resolves to the supplied base. No develop-sync conflict exists. This is a governance blocker, not a Vulture failure. The Vulture-only repair exception does not permit changing reachability grants/ledgers or introducing an artificial consumer.

State transition: prior blocker independently reproduced; focused validation and acceptance review completed. No speculative repair justified.

## Fresh focused results

Executed against the unchanged starting source with 1200-second tool timeouts:

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | 204 nodes: 201 passed, 3 PostgreSQL skips in 1.30s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-reachability.py` | PASS candidate bookkeeping: 1396 modules, 171 unreachable |
| `uv run python scripts/check-reachability-dispositions.py` | PASS candidate bookkeeping: 50 groups |
| `uv run python scripts/check-promotion-surface.py` | PASS, 74 tolerated modules |

Passing candidate bookkeeping does not override failed trusted-base provenance.
No tests added/removed; inventory delta is zero and no new inventory note is required.

## Architecture and acceptance review

Read repository `AGENTS.md` and accepted ADR-081226-a66b, ADR-082526-7f02,
ADR-083126-5e62. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`, immutable
admission provenance, and independent trusted-base authority. No production
activation or competing scheduler/authorization path is introduced.

Production import search finds the codec importing the identity DTO and the
Vulture whitelist importing a type, but no runtime codec consumer.
`PgTaskIdempotencyStore._read` at `packages/maistro-core/src/maistro/tasks/idempotency.py:1180-1191`
still invokes `_row_of`. Tests prove a staged codec contract, not live admission.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Required interfaces, frozen/slotted header, six decode codes, matching scalar header | Source inspection and passing header/schema/mismatch tests in the focused run. |
| Named columns, strict UUID .hex, signed timestamps, #1851 constructors | Passing storage UUID, scalar validation, owner-token and DTO tests. |
| Fresh flat mapping; request/receipt/provenance snapshots preserved | Three state round trips and fresh-mapping tests pass; independent task_id/run_id shape assertions at `test_admission_codec.py:134-137`. |
| Legacy bound/unresolved/partial/receipt-only/announced-without-Run; never invent identity | Passing legacy cases. Bound pairs without receipt remain typed partial evidence because the binding DTO requires a receipt. |
| Header preserves expiry/fingerprint despite full decode failure; unknown versions fail closed | Named header preservation and format rejection tests pass. No clock, incoming fingerprint, assessment, claim or 409 policy exists in codec. Consumer C precedence is not proven here. |
| Strict TEXT JSON, no duplicate keys/nonobjects/bare nonfinite tokens | Invalid JSON tests pass, including direct storage-text injections for excessive nesting, lossy numbers and surrogate corruption. Positive exact-number/Unicode cases pass. |
| Typed error, validated scope only, no raw snapshot/token in displayed exception chain | Scope-key, token hygiene and suppressed-context tests pass. |
| Tagged evidence and unchanged fingerprint | Tag round trips pass; codec preserves tag objects and does not recompute fingerprint. Actual evidence-json producers and model_of/model_of_json materialization remain UNVERIFIED; fixtures construct tag dictionaries. |
| SQL field mapping | Source maps request_snapshot to existing `request` TEXT, owner_token to `claim_token`, bound task_id to receipt identity with run_id. Live migrated-schema execution UNVERIFIED this round. |
| Disposable real migrated PostgreSQL; both DSNs same DB; raw and production codecs | UNVERIFIED: all three DB cases skip at `test_admission_codec.py:470` for missing DSNs. No database sessions, row counts or durability proof claimed. |
| Run text-to-jsonb INSERT stores object; real authorized principals/Workspace/Project and registered Graph kinds | UNVERIFIED by codec fixtures or this execution. |
| No SQL mutation, HTTP mapping, queue/live assessor/scope utility/decision-policy change | Source inspection confirms staged pure codec; this round changes only this report. |
| Focused tests, lint, format, mypy, inventory and full unchanged integration gates | Focused validation passes above; trusted-base provenance FAILS. Full integration CI and live reachability acceptance UNVERIFIED. |
| New meaningful tests with pre-fix/mutation evidence | No tests changed and no new mutation experiment claimed. Existing tests inject storage corruption directly, not mocked transaction outcomes. |

## Reported CI failure and handoff

Inspected all four captured `test` check records in the frozen dispatch snapshot.
The only failed check names `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the
assigned starting head, and supplies null summary/text. Three others succeed.
No assigned-head failing node or traceback is supplied. **UNRESOLVED:** the
focused test pass cannot establish the entire CI `test` job; that job partitions
core tests into the separate coverage producer (`.github/workflows/ci.yml:574`).
No repair is justified by a bare status on another head.

Verdict: **BLOCKED**. The mandatory exact-debt-ledger provenance gate fails at
`.github/workflows/vulture-ratchet.yml:77`. Resolving it requires independently
reviewed trusted-base authorization or separately authorized real consumer
integration, neither permitted in this repair. Vulture already passes: do not
repeat an unchanged-base Vulture repair or add artificial imports/grants.

Changed file: only `docs/testing/issue-1893-repair-6175e98a.md`; commit locally.
No production/test/ledger/gate changes, no GitHub mutation, no work discarded.
Next: provide the assigned-head CI traceback and an authorized resolution of
trusted-base reachability; then revalidate live DB/materialization and full CI.
Progress: checked 1, done 0, skipped 0, errors 1 (provenance gate).
Residual risks: inactive codec, incomplete live DB/model/authorization acceptance,
and missing assigned-head test-failure evidence.
