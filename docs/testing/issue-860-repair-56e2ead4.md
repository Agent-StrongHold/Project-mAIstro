# Issue #860 repair — job 56e2ead4

## Frozen scope

- Issue: #860 only; branch `auto-860` in assigned worktree.
- Starting HEAD: `a774c1d9a653bacabd2fad7c6e4dcc55bad66161` (resolved); base:
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Initial status clean; no incoming edits to salvage.
- Evidence snapshot: supplied dispatch-context.json, prior result 3ac05c76,
  and prior check-3.log from job 98a11313. Current job directory had no
  check-*.log files at initial inspection.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`
  and its production peer, `quality/vulture-baseline.json` only if the mandated
  scan finds reviewed retained debt, and an inventory note if tests change.
- Acceptance inspection: existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, relevant server rate-limit code,
  soak load-profile/evidence documents and governing ADRs. No broader repairs.

## Initial evidence and assumptions

The supplied historical check fails because the schema-fence test expects 21
DDL statements but observes 24. This is not assumed to fail at the current HEAD;
reproduction is required before editing. Prior result records missing production
RC soak evidence; unit tests alone cannot resolve that block. This is a writer
repair assignment, not a verifier-only assignment. No GitHub mutations or
promotion claims will be made.

## Reproduced results

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The reported historical failure is already repaired:
  lines 173–175 explicitly include the three validation audit columns. No test
  weakening or production change is justified.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **PASS**, 1322 findings matching 1322 reviewed identities, zero unclassified
  and never-allowlist findings. Conditional ledger amendment skipped: no debt
  discrepancy exists.
- Initial local dispatch JSON inspection incorrectly treated the integer `issue`
  field as an object (AttributeError); resolved by reading `sources[].data`.
  This was an inspection error, not a validation failure.

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **72 passed**.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **1 passed**.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3301 files already formatted.

All validation batches used 1200-second timeouts. Skipped PostgreSQL tests are
not live database evidence. No long soak was run. No tests were added or changed,
so no inventory delta is required. The only changed file is this handoff.

## Architecture and acceptance disposition

Read repository instructions, `docs/README.md`, ADR-081 (Proposed),
ADR-081626-f383 (Accepted) and ADR-082426-82c7 (Accepted). Occurrence admission
uniqueness does not establish physical execution uniqueness; fencing authority
belongs to the canonical Run store, not a new soak scheduler. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. No runtime authority or policy
change was made. The documented process-local #842 budget is not proof of the
stronger #860 replica-selection criterion; it remains a contract/evidence gap,
not a reason to weaken the promotion gate.

| # | Acceptance criterion | Current evidence and disposition |
| --- | --- | --- |
| 1 | Representative RC workload | **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md:167` documents missing multi-user/Workspace, fan-out, successful tool/model, Design/Canvas and reconciliation traffic. No selected-RC applicability established. |
| 2 | Two supported production replicas | **UNVERIFIED**. Executed two-instance ASGI middleware tests, not the deployed RC topology. |
| 3 | Sustained saturation/reclaim/backoff/leaks | **UNVERIFIED**. Short regression runs do not establish long-window production behavior. |
| 4 | No duplicated physical work | **UNVERIFIED**. `scripts/soak/run_soak.py:1067` cancels the admission probe's queued Run without execution. Admission assertions cannot prove physical Attempt or Goal reconciliation uniqueness. |
| 5 | Replica-independent rate/security/degraded enforcement | **UNVERIFIED with counterevidence**. Executed `tests/test_soak_promotion_gates.py:439`: the same authenticated or unauthenticated identity gets independent `[200, 200, 429]` allowances on each production middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:94` creates the local limiter. |
| 6 | Thresholded production telemetry | **UNVERIFIED**. Passing sampler regressions do not supply production pool/query/lock/loop/queue/error time series. |
| 7 | Active-work kill/restart recovery | **UNVERIFIED**. No deployed physical Attempt recovery experiment executed. |
| 8 | Long soak of exact promoted RC/config | **UNVERIFIED**. `scripts/soak/run_soak.py:744` always rejects host preflight as exact-RC evidence. Passing CLI rejection tests use simulated evidence, not four hours of traffic. |
| 9 | Findings filed/reclassified before promotion | **UNVERIFIED**. This handoff records blockers; no complete milestone disposition established. No GitHub mutations performed. |
| 10 | Hash-bound machine/human production evidence | **UNVERIFIED**. This source-bound validation record is not an immutable production soak evidence pack. |

## Handoff

**BLOCKED**, not merge-ready. The historical schema failure is already repaired;
the mandated exact-debt scan has no unbanked identities. No evidence justifies
another code, test or ledger repair in this bounded round. The previous block
cannot be resolved by rerunning those passing checks.

Next: select the immutable RC/configuration, resolve the replica-budget contract,
complete representative production physical-work/recovery traffic and telemetry,
then execute the long soak and disposition its findings. Do not dispatch another
identical scanner repair as a substitute for those missing prerequisites.

Snapshot accounting: checked 1 issue; done 0 acceptance-complete; skipped 0
issues; validation errors 0; inspection errors 1 (resolved above). Conditional
ledger repair skipped because no discrepancy was observed. This checkpoint is
committed locally; no integration approval is implied.
