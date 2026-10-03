# #860 assigned CI-repair validation

## Frozen snapshot

- Issue #860 only, branch `auto-860`, worktree `/home/dev/Git/wt/auto-860`.
- Verified clean starting HEAD `06a6e147a8b64c8c6d85462bcec1177692d05d22`; supplied base `c0582c4ae02c20ce4848ec46407be4c1eed2eff7` resolves.
- Scope: repository instructions and relevant accepted execution/rate-limit ADRs; existing soak driver, promotion-gate tests, evidence/profile/handoffs; production deployment/rate-limit paths; adjacent persistence/backpressure/rate-limit tests; required vulture checker and emitted identities.
- Edit targets frozen to this handoff and, only if the required checker reports actual unbanked retained identities, `quality/vulture-baseline.json`. No speculative code changes or unrelated reconciliation.
- Initial job-directory snapshot: `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`; no `check-*.log` files. Driver checks are unavailable, not presumed passing.
- Prior supplied result inspected: BLOCKED; preceding sampler repair already committed. No uncommitted work to salvage.

## Assumptions and progress

Writer assignment takes precedence over the generic verifier instruction. No designated immutable promotion RC image/configuration is supplied. Existing host preflight is not a supported replacement for the exact-artifact soak. Preserve previous evidence and validate the CI repair without manufacturing a new finding, ledger amendment, or acceptance waiver.

- Required vulture gate freshly PASSed: 1402 findings / 1402 reviewed identities, zero unclassified/never-allowlist. No ledger amendment is justified.
- Read accepted ADR-081426-1f7c (Attempt runtime identity), ADR-081626-f383 (canonical Run-store fencing), ADR-082426-82c7 (occurrence admission), and ADR-085 (principal rate limiting). No replacement execution/store/authorization authority will be introduced. Admission uniqueness is not physical-effect deduplication, and the fencing ADR explicitly does not define expiry takeover.
- Inspected current profile and regression tests. The profile already retracts the historical shared-limiter claim; the supplied H3 finding is not grounds for another cosmetic edit. Exact-RC, representative-workload and physical-recovery gaps remain explicit.
- Production source inspection confirms `RateLimitMiddleware` constructs a separate `InMemoryRateLimiter` per instance (`rate_limit.py:25-30,73`). The production Compose reference defines two services but uses a local build, not a designated immutable RC digest. No new production deployment executed.
- Fresh focused pytest: **102 passed, 5 skipped in 9.90s**. Includes real middleware replica-selection tests and live uv-child sampler regression. PostgreSQL-dependent skips are not credited as live validation.
- Fresh repository lint and format checks PASS: `uv run ruff check .`; `uv run ruff format --check .` (2624 files).
- Historical-evidence evaluation freshly PASSed its negative assertions: actual driver returns exactly `sustain_duration` and `exact_rc_artifact` for preserved round-6 JSON (90.43 seconds vs 14400); `preflight_artifact_check().ok` remains false.
- Inventory gate PASS: 4198 tests in `tests/`, matches recorded inventory. No production/test/config changes; inventory delta is zero.
- ADR-081 is Proposed, not an accepted waiver of the issue's supported-topology requirements. Production `main.py:478` installs the inspected middleware.

## Executed validation

All validation used 1800-second timeouts in the assigned worktree:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 reviewed, zero unclassified/never-allowlist |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 102 passed, 5 PostgreSQL-dependent skips; 9.90s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 2624 files |
| `uv run python -` importing the real driver and evaluating preserved round-6 JSON | PASS: asserted exact failure list and negative preflight-artifact verdict |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS: 4198 collected, matches inventory |

No live PostgreSQL/Compose load or new soak ran. Existing regression results do not substitute for release acceptance.

## Acceptance disposition

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | PARTIAL: inspected `m3a-load-profile.md`; its remaining-profile-gaps section explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal workers. RC applicability UNVERIFIED. |
| Two application replicas | UNVERIFIED in the production artifact. `deploy/docker-compose.prod.yml:26-60` defines two services; executed ASGI limiter instances and wrapper/child sampler fixtures are not that deployment. |
| Sustained saturation, queue/reclaim/retry/leak observations | UNVERIFIED. Actual evaluator rejects the preserved 90.43-second run vs 14400; no sustained RC load executed. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED. Twelve admission-oracle regression cases pass, but physical effects are not observed; historical occurrence probe cancels its queued Run. Accepted Run-store/Attempt authority preserved. |
| Rate-limit/security/degraded non-bypass | NOT MET for a cluster-wide allowance. Executed production-middleware tests reproduce `[200,200,429]` on each replica for the same identity (both identity classes). Local security/backpressure tests pass; full RC degraded behavior UNVERIFIED. |
| Complete metrics with explicit thresholds | PARTIAL: six sampler regressions pass, including live uv-child RSS/descriptor growth. Application-loop lag, detached/container workers, sustained pool/lock/queue metrics and complete RC threshold evidence UNVERIFIED. |
| Kill/restart during active work, fencing and recovery | UNVERIFIED. Wrapper-exit sampler test is not physical Attempt shutdown/recovery proof; no RC kill/restart performed. |
| Long-running exact-RC soak after changes | BLOCKED. No designated immutable promotion RC image/config supplied. `run_soak.py:635,1465` explicitly rejects host preflight. Executed CLI regressions reject missing/null/preflight artifact records even at four hours. |
| Findings classified/filed before promotion | PARTIAL: existing human evidence retains local earliest-invariant classifications, including F11/F12. No new defect invented; external filing UNVERIFIED and prohibited in this lane. |
| Machine/human evidence tied to exact hashes | PARTIAL: preserved historical JSON contains its old commit/config identities; current evaluator rejects promotion. Fresh exact-RC image/config hash-tied evidence UNVERIFIED. |

## Handoff

**BLOCKED** for #860; not integration approval. Only this report changes. No ledger amendment is warranted by the freshly passing required gate, and no test addition calls for a new inventory note. Prior production, test and raw-evidence files are preserved unchanged. No GitHub mutations, destructive git operations or background commands.

Next requires an owner-designated immutable RC artifact/configuration, resolution of cluster rate-limit semantics with the owning deployment/security lane, production-path workload/physical-effect/metric oracles, and execution/publication of a new >=4-hour soak. Another emulator shakedown cannot resolve this block.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`. CI-repair validation completed; issue acceptance remains blocked. Commit this handoff locally as the writer checkpoint.
