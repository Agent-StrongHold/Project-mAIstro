# Issue #860 — bounded CI-repair handoff (8050016d)

## Scope and disposition

Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`, starting HEAD
`1d5b90e0ab3f578c4566fc234c6dc643b2c29323`; clean on entry. Supplied base
`30144ad0f508a6ee5d67c719ed04df5692fb64ea` resolves; its merge base with HEAD is
`cd5618223cbdd9ac55d40695987e09fd8b4ef184`. Snapshot: issue #860 only, explicit
vulture repair followed by acceptance review. Read dispatch evidence and prior
result without refreshing remote issue/PR lists. No driver `check-*.log` files
were supplied; all checks below were executed anew.

**BLOCKED, not a completed issue repair.** The mandated vulture command passes:
1,338 findings equal 1,338 reviewed identities; zero unclassified or
never-allowlist findings. Repeating with the supplied base explicitly selected
also passes. No unbanked identity exists to repair or bank. The ledger exception
therefore requires no amendment, and no speculative source changes are justified.
Historical whitespace failures also do not reproduce against the supplied base.
Only this handoff changes; no code, tests, gates, ledger or grants changed.
No inventory delta is needed because no tests were added or modified.

## Architecture and reachable evidence

Read repository instructions, the load profile, production Compose topology,
soak evaluator and adjacent tests, production middleware and its application
registration. Accepted ADR-081626-f383 reserves fencing authority for canonical
Attempt leases. Admission uniqueness is not physical-work uniqueness. Accepted
ADR-085 requires principal-keyed rate limits, not a second authentication path.
ADR-081 is Proposed, not an accepted waiver of production-soak acceptance.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` without new authorities.

- `maistro_server/main.py:593` installs `RateLimitMiddleware`; its constructor
  at `api/rate_limit.py:72` creates a process-local limiter. The existing
  authenticated and unauthenticated replica-selection tests passed: the same
  identity receives `200,200,429` separately from each instance. This falsifies
  a shared allowance, not merely a mock counter. The cluster policy decision
  remains explicitly `gap-spec` in `BACKLOG.md:267-280` (engine-116).
- `scripts/soak/run_soak.py:635-646` always returns a failed exact-RC artifact
  check for its host-process runner. A longer invocation cannot change that.
- Importing the current evaluator and applying it to retained
  `evidence/m3a-round6-shakedown.json` returns failed checks `sustain_duration`
  and `exact_rc_artifact`. Its actual duration is 90.43 seconds, minimum 14,400;
  retained HEAD is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this source HEAD.
  This is successful rejection of insufficient evidence, not a successful soak.
- `m3a-load-profile.md:150-164,197-200` identifies missing workload and telemetry
  coverage and distinguishes occurrence admission from physical-work recovery.

## Executed validation

Logs: `/home/dev/maistro/jobs/8050016d4a724c0389f29a25598669f4/`.
All commands below exited 0; skipped tests are not treated as proof.

| Command | Observed outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,338/1,338; matches CI arguments |
| Same vulture command with `RATCHET_BASE_REV=30144ad0f508a6ee5d67c719ed04df5692fb64ea` | PASS, trusted merge base `cd5618223cbd` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 2,943 files |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | 60 passed |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 23 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 34 passed, 6 skipped; PostgreSQL integration not configured |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |
| `git diff --check 30144ad0f508a6ee5d67c719ed04df5692fb64ea...HEAD` | PASS |
| `uv run python` evaluator/hash probes | Assertions pass; `check-evidence.json`, `check-evidence-hashes.json`. Identity is in `hashes`; second probe corrects first probe's null `identity` extraction. |

## Acceptance matrix

| Criterion | Evidence and remaining boundary |
| --- | --- |
| Representative RC profile | UNVERIFIED: documented mix lacks multiple users/Workspaces, Graph fan-out, successful tool/model and Canvas traffic. |
| Two application replicas | UNVERIFIED in production: Compose contract and two ASGI instance tests pass, not a deployed RC soak. |
| Sustained pools/queues/leases/retries/leaks | UNVERIFIED: retained duration rejected; no new long production run. |
| Schedule/task/Run/Attempt/Goal physical-work safety | UNVERIFIED under load: admission probe tests pass, not physical-work fencing or Goal reconciliation proof. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for shared allowance: production-middleware counterexample passes for both identity classes. Backpressure tests pass but cannot establish deployed security under sustained load. |
| Complete telemetry with thresholds | UNVERIFIED in production: real wrapper/child sampler test passes; application-loop latency, detached workers and long-window observations remain absent. |
| Active-work kill/restart/drain/fencing/recovery | UNVERIFIED: no production recovery experiment executed. |
| Long exact-RC/config soak | NOT MET by retained evidence: evaluator rejects artifact and duration. No immutable RC selected and exercised here. |
| Findings classified before promotion | Existing engine-116 finding and backlog consistency checked; classification completeness UNVERIFIED. No GitHub mutations. |
| Human/machine evidence tied to current artifact hashes | UNVERIFIED for production: retained hashes target an older source; current logs prove source validation only. |

## Next action

Do not redispatch a speculative vulture repair for this passing gate. Resolve the
cluster-rate policy through the existing canonical security seam; select the
immutable RC/configuration, complete representative production-path workloads
and telemetry, then execute the required four-hour soak and active-work recovery
on that exact artifact. Neither more unit tests nor a four-hour host preflight
can satisfy that missing production evidence. No production soak was launched
in this round and no environment limitation is claimed as proof of acceptance.

Progress: checked 1 assigned issue; done 1 bounded validation/handoff; skipped 0
issues; errors 0 in executed checks. Issue acceptance remains blocked. Commit
this handoff locally only; no push, integration approval or closure action.
