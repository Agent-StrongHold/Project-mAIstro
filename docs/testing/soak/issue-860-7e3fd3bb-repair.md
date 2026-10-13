# Issue #860 — bounded CI repair (7e3fd3bb)

## Frozen scope

- Only issue #860, assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `56a0d9761d73f4423a06b069779612321810cae3`.
- Supplied base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inputs: captured dispatch-context.json, supplied prior result.json and
  `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`.
  No check-*.log files were supplied in this job directory.
- Work items, in order: reproduce schema-fence test failure; run the specified
  vulture gate and repair only evidenced identities; validate existing soak
  acceptance probes and record remaining acceptance gaps; commit locally.
- Candidate edit paths: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` (only if the exact scan requires it),
  `docs/testing/inventory-notes/m3a-860-merged-schema-fence.md`, and this note.
  Adjacent soak scripts/tests, ADRs, CI configuration and profile documents are
  inspection/validation inputs, not an invitation to expand the repair.

## Initial evidence and assumptions

The historical check-3.log reports 24 schema statements against 21 expected;
that is historical evidence, not assumed current failure. The prior worker
reported BLOCKED on missing exact-RC physical-work soak and independent
per-replica rate allowances. This is a writer round with permission to repair
reviewed vulture debt, not authorization to weaken gates or promote the RC.
All existing committed work is preserved. No remote mutations are permitted.

## Completed CI-repair checks

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Historical failure does not reproduce. The expected
  DDL already includes all three Gauntlet audit fields (lines 177–179). Skipped
  live-DB cases are not evidence of live PostgreSQL correctness.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **PASS**, 1323 reviewed identities / 1323 findings, zero unclassified or
  never-allowlisted findings. No evidenced ledger amendment is needed.

Both commands used a 1200-second timeout. These work items are complete without
code changes; inventing a repair would contradict the fresh evidence. Next is
bounded validation of acceptance gaps, not another clean-gate retry.

## Additional validation

Executed with 1200-second timeouts:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3277 files).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  **80 passed**.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **27 passed**.
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- `uv run python scripts/check-adr-index.py`: PASS.
- `git diff --check`: PASS.

The vulture invocation matches `.github/workflows/quality.yml:1078–1081`.
No tests were added or modified; no suite inventory delta is required.

## Architecture and acceptance evidence

Read repository instructions, documentation authority map, the load profile,
production limiter, schema fence and adjacent tests, and accepted ADRs
ADR-081226-a66b, ADR-081626-f383 and ADR-085. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt model. In particular, lease expiry
in the issue is not authorization to invent takeover: ADR-081626-f383 explicitly
leaves reclaim authority undefined and retains one active ordinary Attempt.
ADR-085 requires principal-keyed rate limits but does not establish shared state.

The freshly executed regression at `tests/test_soak_promotion_gates.py:439`
uses real production RateLimitMiddleware instances with identical client IP and
credentials. Each returns `[200, 200, 429]`; the second replica accepts requests
after the first has exhausted its allowance. This is a counterexample to a
shared allowance, not deployed proof of the full security/degraded criterion.
Production explicitly constructs the in-memory limiter per middleware instance
at `packages/maistro-server/src/maistro_server/api/rate_limit.py:93`.
Do not replace the canonical authorization path or silently reinterpret the
issue's non-bypass requirement to mark it complete.

`scripts/soak/run_soak.py:744` always rejects the host-process preflight as exact
RC evidence. The executed four-hour rejection regression verifies this guard,
not a four-hour run. At line 1067 the schedule probe cancels its admitted Run
through the canonical store without executing physical work. Running this
harness longer cannot fill those acceptance gaps.

| Acceptance criterion | Disposition from this round |
| --- | --- |
| Representative RC workload | UNVERIFIED. Profile explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads. |
| At least two deployed application replicas | UNVERIFIED. Two middleware instances are not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks and shutdown | UNVERIFIED. No long production workload executed; reclaim must respect accepted fencing authority. |
| No duplicate physical work, including Goal reconciliation | UNVERIFIED. Admission-only probe never executes its Run; unit guards do not prove physical uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Non-bypass is not proven: independent per-replica allowances reproduced. Full deployed criterion UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED. Driver loop lag is not application loop lag; mock-backed sampler tests are not production telemetry. |
| Active-work replica restart, graceful drain/fencing/recovery | UNVERIFIED. No deployed active-work restart executed. |
| Long exact-RC artifact/config soak | UNVERIFIED. Preflight rejection guard passes; it does not supply the required RC run. |
| Load findings classified to earliest broken milestone | Backlog consistency PASS; complete load-derived classification UNVERIFIED. No issue mutations performed. |
| Human/machine evidence tied to exact image/package/commit/config hashes | UNVERIFIED. This local validation report is not a hash-bound production soak. |

## Handoff / stop condition

**BLOCKED**, not promotion-ready. Only this report changes. The reported CI
failure is already repaired and the requested identity ledger is exact; no
speculative code, test or ledger edits were made. The remaining work requires
an identified immutable production RC/config, representative physical-work
traffic and complete deployment telemetry, resolution of aggregate rate-policy
semantics at the existing enforcement path, and a fresh >=4-hour exact-artifact
soak. None can be inferred from passing preflight/unit checks.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0, errors 0,
blocked 1. CI-check work items completed. Next: provide the production RC/config
and execute the missing acceptance workload; do not redispatch the historical
schema failure or clean vulture scan as an actionable repair. Commit this report
locally and retain all inherited work. No GitHub mutations or promotion approval.

