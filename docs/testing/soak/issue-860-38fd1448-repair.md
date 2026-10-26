# Issue #860 — repair checkpoint (job 38fd1448)

## Frozen scope

- Issue #860 only; starting HEAD `99c56044705e65772a847065ec92216c1ded8404`, supplied base `ac7370141e8e61bd6f352bca35ed0b505104aadb` both resolve locally.
- Initial worktree clean; no incoming edits to salvage.
- Inspect repository instructions, applicable ADRs, supplied dispatch and prior failure/result, current soak profile/harness and adjacent tests. Run exact vulture gate and focused validation.
- Candidate changes limited to this report and, only for reproduced findings, `quality/vulture-baseline.json`, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, and a corresponding inventory note. No remote mutations or competing execution authorities.
- Current job directory contains no `check-*.log` files. The specifically supplied prior log will be inspected instead; no driver success is assumed.
- Role ambiguity: dispatch explicitly assigns repair and local commit, so proceed as writer, not read-only verifier.

## Progress

The supplied historical `check-3.log` fails the learning-schema fence test (24 DDL statements versus 21). Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passes: **37 passed, 6 skipped** (1.35 s). Historical failure not reproduced; skipped tests are not live PostgreSQL evidence.

Fresh mandated `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passes: **1,322 reviewed identities / 1,322 findings, zero unclassified or never-allowlist**. No actual ledger repair is indicated, so do not amend the ledger merely because the dispatch permits it. Both commands used 1,200-second timeouts.

Read supplied prior result (BLOCKED) and current profile. Acceptance requires actual sustained multi-replica RC evidence, not merely passing static/unit gates. Additional fresh validation (1,200-second timeout):

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 73 passed (2.23 s).

The real production middleware tests reproduce independent allowances on both replicas; the production task-router test reproduces a peer receipt 404. These passing falsification tests do not establish production readiness. The schema test already enumerates the three audit columns absent in the historical failed expectation; no source/test fix is warranted. No tests added or removed, so no inventory delta.

## Architecture reconciliation

Read `AGENTS.md`, the documentation authority map, accepted ADR-081426-1f7c (ExecutionRuntime) and ADR-081626-f383 (lease/fencing), and the profile's cited ADR-081 (deployment, still **Proposed**). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: the runtime owns physical mechanics, not domain scheduling, authorization or persistence authority. The accepted fencing contract explicitly does not define live-Attempt expiry takeover; the issue cannot authorize inventing that behavior in a soak harness.

Current source evidence:

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`: schema upgrades occur inside a transaction with an advisory lock before DDL. The test's independent ordered list includes all three validation audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176`.
- `scripts/soak/run_soak.py:744`: exact-RC check returns false for the host-process preflight. Executed CLI tests reject missing/null/preflight artifact evidence even with a synthetic four-hour duration.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`: explicit process-local enforcement. Executed `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently from both instances for the same identity, authenticated and unauthenticated. Six-path local enforcement is not a replica-selection non-bypass proof.
- `packages/maistro-server/src/maistro_server/api/tasks.py:144`: receipts read the local queue. Executed `tests/test_soak_promotion_gates.py:564` uses canonical admission and separate queues, observing local 200 and peer 404 without hiding either response.
- `docs/testing/soak/m3a-load-profile.md` expressly identifies representative-profile and telemetry gaps. The historical `m3a-soak-evidence.md` marks its evidence provisional; historical runs are not validation of this head.

## Acceptance matrix

| Issue criterion | Fresh evidence / status |
| --- | --- |
| Representative RC profile | **UNVERIFIED**: documented preflight omits concurrent users/Workspaces, graph fan-out, successful tool/model calls, Design/Canvas and Goal traffic without an RC-specific applicability determination. |
| At least two deployed replicas | **UNVERIFIED**: executed ASGI middleware/router tests, not deployed replicas. |
| Sustained saturation, queue growth, reclaim, retry, leaks | **UNVERIFIED**: no long production run executed; reclaim contract also needs resolution. |
| Physical-work uniqueness, admission and Goal reconciliation | **UNVERIFIED**: admission/probe unit tests do not prove physical Attempt execution or Goal reconciliation under sustained load. |
| Replica-resistant rate/security/degraded behavior | **UNVERIFIED** overall; independent replica allowances reproduced; backpressure tests pass but do not prove non-bypass. |
| Production telemetry and explicit thresholds | **UNVERIFIED**: process sampler tests pass, but no fresh production PG/lock/application-loop/worker/queue/error/leak series exists. |
| Active-work replica kill/restart, drain, fencing and recovery | **UNVERIFIED**: cleanup tests are not a production active-work recovery experiment. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**: current harness explicitly cannot establish artifact equivalence. No immutable RC image/configuration is designated by this dispatch. |
| Findings filed/reclassified to earliest milestone invariant | **UNVERIFIED** for completeness; historical classifications are not new production-load findings. No remote mutations performed. |
| Hash-bound machine/human soak evidence | **UNVERIFIED** for promotion: this report records source validation, not a new exact-image/configuration soak. |

## Handoff

**BLOCKED**, not integration approval. The specific CI repair needs no code change: the old failure does not reproduce and the permitted ledger is already exact. Only this report changes. Do not repeat CI-only repair rounds as a substitute for release evidence.

Next requires an immutable RC/effective configuration and a production-artifact workload/telemetry runner, resolution of replica allowance/receipt visibility and reclaim-contract constraints, then the representative >=4-hour soak including physical-work and active-work recovery observations. These requirements cannot be satisfied by extending the host emulator or weakening its gates.

Progress: checked 1 issue, done 0 complete acceptance sets, skipped 0 issues, errors 0 fresh validation commands. No new tests, inventory changes, ledger edits, production changes, or GitHub mutations. Local commit required; final whitespace and worktree verification follows.
