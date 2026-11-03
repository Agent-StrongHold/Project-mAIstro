# Issue #860 — a1b8e8de repair checkpoint

## Frozen scope

- One item: assigned issue #860, branch `auto-860`, starting head
  `de72539046917379f50834594a532c1c7c8dfba5`.
- Assigned base `4fd7801fb333611955dda962d11845aaf065277c` resolves locally.
- Initial worktree clean; no incoming edits to salvage.
- Inspect existing soak runner/profile/evidence, adjacent soak and production
  regression tests, relevant ADRs, and the explicitly assigned vulture gate.
- Edit scope: this report; `quality/vulture-baseline.json` and actual production
  dead-code identities only if the requested scan demonstrates a repair need.
  No scheduler, rate-limit contract, deployment, or unrelated branch changes.
- Job directory `/home/dev/maistro/jobs/a1b8e8de1dd84e5dbbc3239221f42247`
  contains no `check-*.log` files at initial inspection. Run checks directly.
- Previous result is BLOCKED. Its verification claims are inputs, not evidence
  for this round. No deployable RC artifact/configuration identity was supplied;
  do not invent one or treat a host preflight as a promotion soak.

## Progress

Vulture scan executed with CI's exact arguments:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
passed: 1360 reviewed identities / 1360 findings, zero unclassified and zero
never-allowlist findings. Gate selected merge base `045cfdfbe3ea`, candidate
`de7253904691`; this is its actual default provenance, not the assignment base.
There is no demonstrated ledger repair to make. Preserve the ledger unchanged.

Read repository instructions and accepted ADRs: ADR-085 (canonical per-principal
rate limiting), ADR-081626-f383 (Attempt fencing), ADR-082426-82c7 (occurrence
admission is not physical execution), ADR-083026-a91e (absent metrics are not
zero). These prohibit interpreting admission counts as physical-work proof or
inventing missing telemetry. Keep the canonical execution spine unchanged.

The prior misleading H3 shared-store claim is already corrected in
`m3a-soak-evidence.md`; current production middleware explicitly owns an
`InMemoryRateLimiter` per instance. Existing tests exercise that real middleware
with the same identity on two instances; execution passed as recorded below.
No GitHub mutations or background work.

## Executed validation

All commands ran in the assigned worktree with 1200-second tool timeouts.

| Command | Actual outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1360/1360 identities, no repair required |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2809 files already formatted |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs` | 80 passed, 5 skipped in 2.28 s |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; shipped-surface truth matrix complete |
| `uv run python -` importing `scripts/soak/run_soak.py` and calling `failed_promotion_checks` on the three frozen historical packs below | PASS: assertions that every pack fails both duration and exact-artifact gates |

The five skips are PostgreSQL integration cases at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:766,877,896,906,917`:
`MAISTRO_TEST_PG_DSN` is not set to a migrated database. No fresh database race,
Compose deployment, provider call or soak was executed in this round. Unit tests
of SQL fencing do not substitute for that missing integration evidence.

Historical evaluator results (raw packs unchanged):

- `m3a-soak-evidence.json`: duration absent at top level; failures:
  `rate_limit_enforced`, `lb_failover_bounded`, `nonterminal_runs_after_settle`,
  `task_admission_availability`, `sustain_duration`, `exact_rc_artifact`,
  `graceful_drain`.
- `m3a-round5-final.json`: 90.17 s; failures: `rate_limit_enforced`,
  `sustain_duration`, `exact_rc_artifact`.
- `m3a-round6-shakedown.json`: 90.43 s; failures: `sustain_duration`,
  `exact_rc_artifact`.

This executes the current evaluator against existing records, not a rerun of the
recorded traffic. Historical `rate_limit_enforced=true` does not prove today's
six-path probe or a shared allowance.

## Acceptance audit

| #860 criterion | Evidence and disposition |
|---|---|
| Representative RC profile | PARTIAL / UNVERIFIED: inspected `m3a-load-profile.md` and runner request paths (`run_soak.py:728-759`). One API key, synthetic receipt reads, absent model provider, no representative multi-Workspace/fan-out/Design/Canvas workloads. Documented gaps are not waivers. |
| At least two application replicas | UNVERIFIED for RC: `deploy/docker-compose.prod.yml:26-79` defines two replicas. Existing packs represent host processes; no fresh deployed-artifact test executed. |
| Sustained saturation, growth, reclaim, backoff and leaks | UNVERIFIED: current evaluator rejects the historical short packs. Sampler subprocess regression passed, proving child RSS/descriptor observation only, not long-window application health. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | UNVERIFIED: HTTP admission-oracle regression passes, but `run_soak.py:982-1068` races admission and cancels its probe Run. No executed physical-work/lease/Goal reconciliation proof across deployed replicas. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared allowance: executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated identities; each real limiter instance returns 200,200,429 independently. `rate_limit.py:25-30,73-78` explicitly implements local state. Six-path probe tests establish local enforcement, not cluster-wide non-bypass. Full security/degraded load acceptance UNVERIFIED. |
| Complete telemetry with explicit pass/fail thresholds | UNVERIFIED: inspected queries at `run_soak.py:465-485` and driver-loop sampling at `1304-1312`; these do not measure application event-loop latency or physical worker recovery. Profile still lists soft expectations, not complete promotion thresholds. |
| Active-work kill/restart, graceful drain, fencing/recovery | UNVERIFIED: historical run 6 records exit/rejoin and drain, but not correlated in-flight Attempt effects. No active-work recovery test executed this round. |
| Long-running exact RC artifact/configuration, rerun on changes | NOT MET: `run_soak.py:635-646,1465` always emits failed artifact check; executed CLI regression rejects otherwise-passing four-hour preflight fixtures. `m3a-round6-shakedown.json:221-224` is 90.43 s against 14400 s. No promotable immutable image/config identity supplied. |
| Findings filed/reclassified to earliest milestone | PARTIAL / UNVERIFIED externally: local evidence pack classifies findings, including F11/F12 as M3-A evidence validity. No external filing performed or verified; GitHub mutations prohibited. |
| Human/machine evidence bound to image/package/commit/config hashes | PARTIAL / UNVERIFIED for promotion: historical packs and prose exist, but production-image/config equivalence is absent and the current artifact gate rejects every inspected pack. |

## Reconciliation and handoff

The topology ADR-081 is **Proposed**, not accepted release authority; the actual
production Compose file is the inspected multi-replica claim. Accepted ADR-085
requires principal-keyed limiting but does not establish cluster-shared storage.
Do not silently weaken #860's replica-selection criterion to make #842's local
contract pass. Resolve that deployment/acceptance mismatch explicitly before
promotion, retaining the canonical principal resolver. No competing scheduler,
execution authority, Goal store, event authority or authorization path added.

**Verdict: BLOCKED.** The assigned CI repair has no reproducible scanner failure.
Only this report changed; no runtime, configuration, tests or ledger changed.
No inventory delta is required because no tests were added/removed. No guessed
ledger amendment, speculative runtime repair, or cosmetic evidence rewrite.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 executed command failures (5 integration tests skipped). The CI scan
subtask is complete. Next: supply the exact RC image/configuration and provider
setup, complete representative workloads and application telemetry, resolve the
rate-limit mismatch, then run and publish at least four hours with correlated
physical-work recovery evidence. Do not rerun the host preflight merely to spend
four hours: it cannot certify the production artifact. Commit this report locally
and leave the worktree clean; no integration or issue-closure approval.
