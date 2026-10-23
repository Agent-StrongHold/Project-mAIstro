# Issue #860 — bounded repair validation (4564bf78)

## Frozen scope

- Item: issue #860 only; branch `auto-860`.
- Starting head: `849980f0671169b82fcddd3168f131fa4f3aa6ac`.
- Supplied develop base: `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
- Worktree was clean; no salvage was necessary.
- Inputs: supplied dispatch-context.json, prior job result if present, repository
  instructions, applicable ADRs, current soak runner/profile/evidence and adjacent
  tests, production rate limiter and Compose configuration, vulture gate/ledger.
- Authorized edit scope: this validation record; genuinely dead identities or
  reviewed retained vulture ledger rows only if the requested scan finds them.
  No test additions planned unless a concrete repair requires them.
- No driver check-*.log files were present in the supplied job directory at start.
- Assumption: this is a writer CI-repair round, not permission to change unrelated
  production contracts or weaken promotion gates. Prior blocked reports are not
  acceptance evidence for this head.

## Progress

Requested exact vulture scan passed: 1336 reviewed identities match 1336
findings, zero unclassified and never-allowlist findings. The trusted baseline
resolved to the supplied base. No ledger amendment or dead-code removal is
supported by this result. Prior result read; its claims still require fresh
acceptance checks. No GitHub mutation or integration approval is authorized. The production model remains Goal -> Graph -> Run ->
NodeRun -> Attempt.

Fresh checks: `uv run ruff check .` passed; `uv run ruff format --check .`
passed (3003 files); `uv run pytest tests/test_soak_promotion_gates.py -x -q`
passed (52 tests); `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py
packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
passed (23 tests). Assigned base resolves; `git diff --check
56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD` passed, so prior whitespace
findings are not reproduced. All shell validations use 1200-second timeouts.

Read accepted ADR-081226-a66b (lifecycle), ADR-081626-f383 (fencing), and
ADR-082126-f69c (recurrence). Admission uniqueness is not physical-effect
uniqueness. Lease-expiry takeover is explicitly outside the accepted fencing
contract; do not invent reclaim authority to satisfy the issue. ADR-081 is
Proposed; the Compose reference does not select an immutable RC artifact.

## Remaining executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed; arguments match
  `.github/workflows/vulture-ratchet.yml:82–85`.
- `uv run python scripts/check-ratchet-provenance.py`: passed, including
  delegated gates; nonfatal SyntaxWarnings and local HTTP CORS warnings.
- `uv run python scripts/check-suite-inventory.py`: passed, 15 suites,
  27048 unique identities, no duplicate evidence. No tests added or modified,
  so no inventory delta is needed.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- Inline `uv run python -` loaded the current `scripts/soak/run_soak.py` with
  importlib and parsed `evidence/m3a-round6-shakedown.json`. Asserted that
  `failed_promotion_checks` returns exactly `sustain_duration` and
  `exact_rc_artifact`, and that `preflight_artifact_check()['ok'] is False`.
  Printed observed duration 90.43 seconds, minimum 14400, and evidence commit
  `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head.
- Production reachability checked: `maistro_server/main.py:628` installs
  `RateLimitMiddleware`; `api/rate_limit.py:72–77` constructs its process-local
  limiter. `run_soak.py:1465` emits the preflight artifact failure and line 1649
  calls the evaluator used by the CLI. These are not unused helper findings.

## Acceptance matrix

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `m3a-load-profile.md:152–163` still identifies missing multi-user/Workspace, Graph/tool/model, Canvas and Goal/background-worker workloads. A profile exists but is not representative RC proof. |
| At least two application replicas | **UNVERIFIED for RC.** `deploy/docker-compose.prod.yml:24–77` defines two replicas; executed ASGI tests instantiate production middleware twice, not the deployed RC. |
| Sustained saturation, queue/reclaim/retry/leak observations | **UNVERIFIED.** Executed evaluator rejects the historical 90.43-second observation against 14400 seconds (`evidence/m3a-round6-shakedown.json:221–224`). Sampler tests passing do not establish long-window application health. |
| Unique physical work across schedule/task/Run/Attempt and Goal reconciliation | **UNVERIFIED.** Historical schedule probe cancels the admitted Run (`evidence/m3a-round6-shakedown.json:12–16`). Admission uniqueness does not prove executed physical-effect fencing or sustained reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT MET for a shared principal budget.** Both authenticated and unauthenticated counterexamples passed (`tests/test_soak_promotion_gates.py:439–488`): replica 1 returns `[200, 200, 429]`, replica 2 independently returns `[200, 200, 429]`. Production explicitly documents this local scope (`api/rate_limit.py:25–30`); do not silently redefine it. Broader concurrency/security proof is UNVERIFIED. |
| Full required telemetry with thresholds | **UNVERIFIED.** Profile contains partial thresholds, but driver loop lag is not application loop lag; worker, saturation, reclaim and long-window measurements remain missing (`m3a-load-profile.md:157–163`). |
| Active-work kill/restart drain/fencing/recovery | **UNVERIFIED.** Historical process exit/rejoin and terminal counts are not physical-effect loss/duplication observations on this RC. |
| Long soak of exact RC artifact/configuration | **NOT MET by supplied evidence.** Current evaluator rejects both duration and artifact. `run_soak.py:635–646` unconditionally identifies this runner as host preflight, not production Compose. Four-hour preflight CLI rejection tests passed. |
| Findings classified to earliest broken invariant | **UNVERIFIED for completeness.** Historical classification exists in the profile, but no fresh representative run establishes the complete findings. No issue filing performed: GitHub mutations are prohibited. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for current RC.** Historical JSON/profile exist, but JSON commit differs from the assigned head and host preflight cannot establish the promoted image/configuration identity. |

## Disposition

**BLOCKED**, not integration approval. The assigned scanner mismatch is not
reproducible. No matching ledger rows were changed, no speculative production
repair was made, and no gates were weakened. Only this report changed.

Next prerequisite is a selected immutable RC image/configuration and a
promotion-capable deployed workload through the canonical execution spine,
including physical-effect observations and application telemetry. Resolve the
replica-budget acceptance gap, then run a fresh >=4-hour soak. Repeating or
extending host preflight cannot discharge the artifact gate. No new load run
was started; this report does not claim that Docker, credentials or connectivity
were unavailable.

Progress: checked 1; done 0 (issue acceptance); skipped 0; validation errors 0.
The local report commit is a writer handoff only. No remote mutation occurred.
