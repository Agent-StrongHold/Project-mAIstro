# Issue #1893 repair checkpoint — c0d5ea2c

## Frozen scope

- Only issue #1893, branch `auto-1893`, starting head
  `80171ce1cff9ca45eaf000bf52569875643a5ba0`, supplied develop base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Worktree initially clean; no incoming uncommitted work to salvage.
- Evidence: supplied dispatch-context.json and check-0.log through check-4.log,
  plus supplied prior result (if present). No GitHub refresh or mutation.
- Production inspection: tasks/admission_codec.py, runs/admission_identity.py,
  adjacent idempotency/evidence-json implementation, their focused tests and
  relevant ADRs, workflows and quality-gate scripts.
- Potential edits limited to those codec/type tests and implementation if an
  actual defect reproduces, corresponding inventory note if tests change,
  explicitly permitted vulture ledger if retained unbanked identities exist,
  and this report. Other quality ledgers/grants are not authorized edits.

## Assumptions and status

Writer role follows the explicit repair assignment. The generic `test: failure`
contains no failing node; inspect supplied evidence before choosing a repair.
Previous reachability authorization blocker is not assumed resolved. No
production activation or competing execution/authorization path is authorized.
Initial item: reproduce the reported failure and establish whether repair is
possible within this lane.

## Recorded results (starting source SHA above)

- Supplied check-0 through check-4 logs show successful dependency sync,
  lint, format, 346 passed / 3 skipped focused tests, and 16567 inventory
  nodes. They contain no failing test node. Prior result is historical only.
- Executed CI-exact Vulture command: 1322 findings = 1322 reviewed identities,
  unclassified 0, never_allowlist 0; passes. No ledger amendment is justified.
- Executed `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb
  uv run python scripts/check-ratchet-provenance.py`: fails on exactly the
  two NEW unreachable admission modules and their two NEW dispositions.
  All other sub-gates pass. The supplied base resolves locally.
- Executed `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed, 3 skipped. Skips are not database durability evidence.

The outstanding blocker is reproduced, not repaired: no reachability grant or
ledger edits are authorized here. Production docstrings explicitly identify
both modules as inactive leaves. Wiring a fake caller or the separate C
consumer to bypass the gate would violate the issue's stage constraints.
Generic hosted `test: failure` remains unattributed at this exact source SHA.

- Independently executed `uv run ruff check .`: pass.
- Independently executed `uv run ruff format --check .`: 3301 files pass.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: pass (2 files).
- `uv run pytest packages/maistro-core/tests -x -q`: exit 0,
  15494 passed, 1070 skipped, 3 xfailed, 54 warnings in 236.12s;
  log `/tmp/1893-c0d5-core.log`. Warnings include aiosqlite worker threads
  encountering closed event loops; a passing suite does not erase these.
  No failing core test reproduced. This is not full hosted integration CI.
- `uv run python scripts/check-shipped-surface-truth.py`: pass.
- `uv run python scripts/check-reachability.py`: pass against candidate
  ledger, 1403 production modules / 171 unreachable. This does not supersede
  the failed trusted-base provenance check.
- `uv run python scripts/check-reachability-dispositions.py`: pass, 50 groups
  classify 171 unreachable modules (149 CONNECT, 20 LIBRARY, 2 RETIRE).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: pass, 16567 unique nodes, zero duplicates.
- In-memory mutation control via `uv run python`: replace encoder output
  `task_id` with NULL, then invoke pytest for
  `test_v2_round_trip_preserves_all_snapshot_bytes`. The bound and acknowledged
  variants fail at test_admission_codec.py:134; unbound passes (2 failed,
  1 passed, 128 deselected). Expected pytest exit 1 observed; the wrapper
  exits 0 only on that expected failure. No source file was mutated.

## Architecture and acceptance review

Read Accepted ADR-082526-7f02 (immutable admission provenance, dispatch identity
on Attempt), ADR-082826-b601 (canonical consumer, explicit eligibility, no
parallel execution authority), and ADR-083126-5e62 (trusted-base policy cannot
be weakened by candidate evidence). They agree with this leaf's pure codec
boundary. The issue's request to pass integration gates cannot override
trusted-base authorization; no new runtime consumer is authorized here.

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header, six decode codes, strict scalar/schema checks and header/row agreement | Source inspection and executed focused codec/identity tests; all non-PG tests pass. |
| Exact immutable v2 DTOs and fresh flat SQL mapping; strict UUID hex and signed timestamps | Executed round-trip, owner-token, generation, scalar and schema tests. Binding shape independently checked at test line 134, mutation control fails there. |
| Legacy bound/unbound/partial distinction; no invented identity | Executed legacy binding, receipt-only, bound-without-receipt, unreadable-evidence and completed-at-not-read tests. Canonical binding requires explicit receipt identity; absence is partial rather than fabricated. |
| Header expiry/fingerprint survive bad snapshots and partial binding; unknown format fails closed | Executed tests at test_admission_codec.py:187-259; codec takes no clock or incoming fingerprint. Actual replacement/409 decision remains separate C/F2 scope, not proven here. |
| Strict JSON, tagged nonfinite and arbitrary permitted evidence, no fingerprint recomputation | Executed JSON/tag/precision/Unicode tests, including nested invalid snapshots and suppressed parsing context. Materialization through real TaskResponse/Run models is UNVERIFIED; existing tag tests use mapping snapshots. |
| Safe errors and validated scope | Executed malformed snapshot, invalid scope, token and schema tests; source raises suppressed parsing exceptions with safe messages. |
| Named SQL columns and TEXT independence across raw/production pools | Test implementation inspected at test_admission_codec.py:448-573. Three database variants SKIPPED locally; migrated DB round-trip, session identities, final SQL counts and Run JSONB object storage are UNVERIFIED this round. Historical claims not adopted. |
| Explicit principals, authorized Workspace/Project, registered Graph | UNVERIFIED as production admission. Codec tests use inert identity strings and make no authorization call; no transaction/dispatch invariant claimed. |
| No SQL mutation, HTTP/queue/assessment/scope-policy change or competing execution authority | Production codec/type inspection: pure DTO conversion only; source docstrings explicitly say no production consumer yet. No production file changed this round. |
| Inventory/lint/format/types/quality | Executed results above. No tests added or removed, so inventory delta is zero and no inventory note is required. Provenance gate still FAILS. |
| Reachable production acceptance/full required integration CI | UNVERIFIED: these are inactive contract leaves; passing test imports are not runtime reachability. Hosted generic test failure remains UNRESOLVED without an attributable failing node in supplied check logs. |

## Handoff

Only this report changed. No code defect reproduced, so no speculative source,
ledger or cosmetic repair was made. Inherited branch content was preserved.
The campaign must resolve the two reachability authorizations through the
protected-base process (or explicitly coordinate a real consumer integration)
before another repair pass can clear provenance. A production-source import
search finds only the codec importing the identity types and a Vulture whitelist
import; neither is a shipped runtime consumer. This worker cannot grant or
activate that integration. Do not loop the same generic `test: failure`
without a current failing node/log and source SHA.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 1 blocking
gate. Next: campaign authorization/coordination, then actual integration CI
and required disposable-PostgreSQL evidence. This report is the sole local
handoff commit; it is not an implementation completion or merge approval.
