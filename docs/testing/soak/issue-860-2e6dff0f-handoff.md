# Issue #860 repair checkpoint (job 2e6dff0f)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`49e62d0cfc8b62abff71782694e54c98445e2007`, base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Initial worktree clean. No incoming uncommitted work to salvage.

Files to review: repository instructions, supplied dispatch context and prior
failure log/result, relevant execution/rate/promotion ADRs,
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`docs/testing/soak/m3a-load-profile.md`, the prior e290159d handoff,
`scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json`, and CI
workflow arguments. Repair surface: this handoff and only identities actually
reported by the prescribed vulture scan (if any). Existing soak implementation
and tests will be validated, not expanded into a new runtime authority.

Ambiguity: assignment is a writer CI repair, while the generic prompt also
mentions verifier mode. Proceed as writer, with a local commit required.
The current job directory contains no driver `check-*.log` files. The explicitly
supplied historical `check-3.log` is available and will be inspected.

The prior result is BLOCKED on exact-RC deployment and evidence, not assumed
resolved by any deterministic CI success. No release candidate will be invented.

## Validation

Prescribed Vulture command freshly passed: 1323 findings, 1323 reviewed
identities, zero unclassified/never-allowlist findings. Arguments match
`.github/workflows/quality.yml:1078–1081`; checker selected ratchet base
`4aa68edc0b6b`. No retained unbanked or removed identities were reported, so
there is no evidence justifying a ledger amendment.

Historical `check-3.log` is an assertion failure in the learning-schema test
(24 statements versus 21 expected), not a Vulture failure. Fresh focused tests passed (see below).
Read all ten criteria from the frozen issue body. Latest three captured comments
only report blocked attempts; they do not supply an immutable RC designation.
No remote lists refreshed. No promotion claim.

Fresh validation, all commands with 1200-second timeouts:

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 reviewed identities, no ledger repair needed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 103 passed, 6 skipped in 2.53 s; skips require `MAISTRO_TEST_PG_DSN`; transcript `/tmp/issue-860-2e6dff0f-pytest.log` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files already formatted |

The schema test independently expects all 24 ordered DDL statements, including
validation audit columns (`test_pg_learnings.py:174–178`). Its passing result
is not a live database concurrency proof. No test or test count changed, so no
inventory delta is needed.

## Architecture reconciliation and acceptance

Read repository instructions, documentation authority map, ADR-081426-1f7c,
ADR-081626-f383, ADR-082526-b36a, ADR-082826-08f0 and ADR-085.
Keep `Goal -> Graph -> Run -> NodeRun -> Attempt` authoritative. Physical
execution identity is Attempt, not Run. The later reclaim/recovery ADRs extend
the original lease ADR: a live lease refuses redispatch, lapsed leases recover
through the canonical lifecycle seam. No new authority or scheduler introduced.

Production installs `RateLimitMiddleware` at `main.py:648`; it resolves the
canonical principal but owns process-local limiter state (`api/rate_limit.py:31–37,
90–98`). Fresh `test_replica_selection_has_an_independent_production_allowance`
(`tests/test_soak_promotion_gates.py:439`) proves each instance accepts two
requests then rejects the third, for the same identity, authenticated and
pre-auth. This is a real middleware ASGI probe, not deployed replica evidence.
The stronger issue non-bypass claim remains unproven; no new rate-policy or
coordinated-store implementation is justified by the passing CI gate.

| Acceptance criterion | Fresh evidence / remaining disposition |
|---|---|
| Representative release workload | **UNVERIFIED.** `run_soak.py:1373–1395` uses one credential and health/task/receipt/metrics traffic without LiteLLM; `m3a-load-profile.md` documents absent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and background reconciliation. RC applicability is not designated. |
| At least two production replicas | **UNVERIFIED for RC.** `run_soak.py:730–741` explicitly identifies host-uvicorn preflight, not the promoted deployment. Two ASGI middleware instances are not two deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks | **UNVERIFIED.** Sampler and admission tests pass; no sustained RC observation window executed. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal | **UNVERIFIED.** Admission tests pass; `run_soak.py:1507–1527` checks logical Run counts/status, not all physical Attempt executions. |
| Rate/security/degraded non-bypass | **UNVERIFIED for deployment.** Fresh production-middleware test reproduces independent per-replica allowances. Direct-burst enforcement does not establish a shared principal budget. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** `run_soak.py:1410–1426` measures driver-loop latency, not application event-loop latency; no complete production telemetry window collected. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED.** Evaluator tests pass, but no active RC Attempt was killed and observed through canonical recovery in this round. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** No immutable RC designation supplied. Fresh four-hour-preflight CLI tests reject missing/null/preflight artifact evidence; production unconditionally installs the failing artifact check at `run_soak.py:1552`. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Local findings recorded here; GitHub mutations forbidden and not attempted. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC.** This report binds local validation to a source head only, not a promoted image/configuration or long soak evidence pack. |

## Handoff

**BLOCKED.** Only this handoff changed. No source, tests, ledger, grants or gates
changed: both the historical schema failure and requested Vulture debt fail to
reproduce. Existing work is preserved. A synthetic or short host-process run
cannot close the acceptance gaps, so no such run is presented as promotion proof.

Next action requires the release owner to designate immutable RC artifacts and
configuration plus representative workload applicability. Resolve rate non-bypass
semantics through existing policy ownership, then execute the long production
soak with physical Attempt/recovery observations and complete telemetry. Any
code/runtime-config change requires a new soak. Repeating this CI-only repair
without those prerequisites cannot resolve #860.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate RC and execute production soak"}`.

