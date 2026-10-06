# Issue #860 — repair checkpoint (391707f3)

## Frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head: `7dcfacb7a1cdb3d22b7808fbcc93b208e607443d` (verified); base: `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
- One item only: issue #860, including the explicitly assigned vulture exact-debt-ledger repair.
- Inputs: supplied `dispatch-context.json` and prior result `8583ecf3563c41f38f44acbd0f572fa0/result.json`; no remote refresh.
- File scope: this report; `quality/vulture-baseline.json` and production identities only if the exact scan demonstrates a needed repair; existing soak runner, profile, evidence, promotion tests, relevant ADRs and gate implementation for read-only acceptance review.
- Initial worktree clean; no salvage needed. No driver `check-*.log` files were present in the supplied job directory at inspection.
- Assumption: this is the writer CI-repair lane, not a verifier-only invocation. Prior BLOCKED status is evidence to recheck, not authority to declare readiness.

## Progress

Exact assigned vulture scan executed successfully (exit 0): 1336 reviewed identities and 1336 findings; zero unclassified or never-allowlist findings. Trusted baseline resolved to the assigned base. There is no demonstrated ledger mismatch or dead-code regression to repair; no ledger amendment is warranted. The supplied issue has ten acceptance criteria; the current profile explicitly describes host preflight rather than an exact-RC deployment. Focused validation completed: ruff lint/format, 52 soak-gate tests, 23 server rate-limit/backpressure tests, ratchet provenance, shipped-surface truth, and suite inventory all passed. The current evaluator rejects retained evidence for `sustain_duration` and `exact_rc_artifact`. Detailed acceptance mapping follows below.

## Architecture reconciliation

Read repository `AGENTS.md`, `docs/README.md`, accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle), ADR-081626-f383 (execution lease/fencing), and ADR-082126-f69c (recurrence produces Runs). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; deduplicated admission and a terminal Run are not proof of unique physical work. The lease ADR explicitly does not define expiry takeover; this issue does not authorize inventing reclaim authority. ADR-081 is **Proposed**, not an accepted deployment mandate. The checked-in production Compose file is a reference topology, not identification of a selected immutable release candidate.

The production app installs `RateLimitMiddleware` at `packages/maistro-server/src/maistro_server/main.py:628`. Its constructor creates `InMemoryRateLimiter` (`api/rate_limit.py:72`); the documented process-local scope at lines 25–30 explains the observed independent allowances. This lane does not silently redefine that contract or add a second authorization path. The stricter #860 non-bypass acceptance remains unsatisfied for a shared principal budget.

## Executed validation

All commands used the assigned worktree and a 1000-second tool timeout. No remote mutations or background commands were run.

| Command | Outcome |
| --- | --- |
| `git rev-parse HEAD` and `git status --short` | Assigned starting head verified; clean before this report |
| `git rev-parse --verify 56332162cf636e9a1e8a7e346101803ed6ec7b1f^{commit}` | Base exists |
| `git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD` | Passed; prior whitespace finding not reproduced against assigned base |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1336 matching identities, no repair indicated; matches workflow arguments |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed: 3003 files formatted |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 52 passed, including CLI rejection of four-hour preflight, child-process resource sampling, direct-replica enforcement and independent-allowance counterexample |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 23 passed |
| `uv run python scripts/check-ratchet-provenance.py` | Passed including delegated gates; nonfatal SyntaxWarnings and local HTTP CORS warnings |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed |
| `uv run python scripts/check-suite-inventory.py` | Passed: 15 suites, 27048 unique test identities, no duplicated evidence |
| `uv run python -` importing the current soak evaluator and loading retained round-6 JSON | Asserted failures include both `sustain_duration` and `exact_rc_artifact`; actual returned list contains exactly those two; preflight artifact check asserted false |

The inline evaluator probe also printed `evidence.get('artifact') == None`; identity actually lives under `hashes`, inspected separately rather than inferring that all provenance is absent. `hashes.git_head` is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c` (`evidence/m3a-round6-shakedown.json:70`), not the assigned starting head.

## Acceptance matrix (all ten issue criteria)

| Criterion | Evidence and conclusion |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** Profile exists, but `m3a-load-profile.md:152–163` explicitly lacks multi-user/Workspace, Graph fan-out, successful tool/model, Canvas and reconciliation workloads. No selected RC configuration was exercised here. |
| At least two deployed application replicas | **UNVERIFIED for RC.** `deploy/docker-compose.prod.yml:24–77` defines two replicas; passing ASGI middleware tests are not a deployed multi-replica soak. Host preflight cannot establish image equivalence. |
| Sustained saturation, reclaim, retries and leak observations | **UNVERIFIED.** Retained run records 90.43 seconds at JSON line 165, versus 14400 required at lines 221–224. Passing resource-sampler tests validate the measurement mechanism, not long-window application behavior. |
| No duplicate physical work; schedule/task/Run/Attempt and Goal safety | **UNVERIFIED.** Round-6 schedule probe cancels its queued Run (JSON lines 12–16); admission identity checks do not execute and fence physical effects or prove sustained Goal reconciliation. |
| Rate/security/degraded concurrency non-bypass | **NOT MET for a shared allowance.** Both authenticated and unauthenticated counterexamples at `tests/test_soak_promotion_gates.py:439–488` passed: replica 1 gives `[200, 200, 429]`, then replica 2 grants another `[200, 200, 429]` for the same identity. Broader production degraded/security behavior remains UNVERIFIED. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** Profile includes thresholds and partial instrumentation, but driver loop lag is not application loop lag and required worker/reclaim/saturation observations are absent (`m3a-load-profile.md:157–163`). |
| Kill/restart during physical work with drain/fencing/recovery | **UNVERIFIED.** Retained process exit/rejoin and terminal counts do not demonstrate in-flight physical-effect uniqueness or loss-free recovery on current RC. |
| Long soak of exact RC after runtime changes | **NOT MET by supplied evidence.** Executed current evaluator rejects duration and artifact; `run_soak.py:635–646,1465,1649` connects unconditional host-preflight rejection to production driver output and CLI evaluation. A longer host run cannot satisfy this. |
| Findings classified to earliest broken milestone invariant | **UNVERIFIED for completeness.** Existing profile has historical classifications, but no new representative production run establishes a complete finding set. No GitHub filing performed (prohibited). |
| Machine/human evidence bound to exact artifact/config hashes | **UNVERIFIED for current RC.** Historical JSON and profile exist, but recorded commit differs and promoted application image/configuration identity is not established by this preflight. |

## Disposition and handoff

**BLOCKED.** The assigned CI mismatch is not reproducible; changing a matching ledger would be cosmetic and unsupported by actual evidence. Only this report changed. No tests added or changed, so no inventory delta note is needed; the inventory gate confirms no count change.

Next work requires an explicitly selected immutable RC image/configuration, a representative workload through the canonical execution spine with physical-effect observations and application telemetry, resolution of the replica-budget contract gap, and a fresh >=4-hour deployed soak. This is not a request to weaken the artifact gate or replace canonical execution authority. No new load run was attempted because the available host runner is structurally unable to sign exact-RC evidence; environment credentials/connectivity were not asserted missing or unavailable.

Progress: checked 1, done 0 (issue acceptance), skipped 0, validation errors 0; next: exact-RC execution/evidence work, not speculative vulture repair. Local report commit is the writer handoff, not integration approval.
