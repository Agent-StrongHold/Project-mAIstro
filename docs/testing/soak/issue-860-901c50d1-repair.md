# Issue #860 — repair job 901c50d1

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `2a992ec1cdd48a46856746b081f88e5c839f4d6e`; initial worktree clean.
- Sole issue: #860, using the supplied acceptance snapshot; no GitHub mutations.
- Inspect existing soak profile/evidence, `scripts/soak/run_soak.py`, adjacent promotion/production-stack tests, changed pg-learnings/task-admission paths and tests, rate-limit production path, relevant repository instructions/ADRs and quality workflows.
- Potential edits restricted to evidence-backed repairs in those paths, their inventory notes, this report, and (only if exact scanner findings require it) `quality/vulture-baseline.json`.
- The supplied job directory contains no `check-*.log` files at initial inspection. No driver validation claims can be verified from those absent logs.
- Prior result artifact read: job 13ec34d7 reported BLOCKED; its claims will be independently checked.

## Progress

Snapshot complete. Assumption: this is the writer CI-repair lane; sustained production acceptance must remain unverified unless observed, not inferred from unit tests.

- Exact requested vulture command PASS: 1359 findings / 1359 reviewed identities; zero unclassified and zero never-allowlist. No ledger or source amendment is justified.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info` FAIL (exit 1): cannot connect to daemon. Production Compose execution remains blocked; no retries or speculative host repair.
- Current rate-limit implementation explicitly has independent replica budgets (`rate_limit.py:25-30`); profile phase 5 already disclaims cluster-wide enforcement. No stale shared-store wording repair needed.
- Host preflight rejects exact-artifact promotion in `run_soak.py:635-646`. Longer execution cannot remedy that topology mismatch.
- One inferred ADR filename was not found; skipped. Resolve the lease-renewal ADR by its exact filename before reading. No unresolved git ref was executed.
- No source/runtime configuration/test changes made.
- Repository instructions and relevant ADRs read: ADR-081 (Proposed deployment profile), ADR-085 (Accepted per-principal rate limiting), ADR-081626-f383 (Accepted store-owned Attempt fencing), and the resolved ADR-082526-b36a (Accepted renewal/reclaim). The latter adds reclaim to the older fencing boundary; reclaim is not assumed absent. No competing execution/authorization authority introduced. The issue's replica-selection requirement remains unresolved against the documented per-process allowance; it is not waived by ADR-085.

## Executed validation

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1359/1359 reviewed identities, no debt amendment needed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 2770 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 88 passed, 5 skipped in 2.89s; all skips require `MAISTRO_TEST_PG_DSN` |
| `uv run python scripts/check-deployment-claims.py` | PASS, component existence only |
| `uv run python scripts/check-execution-lifecycles.py` | PASS, 19 classified/discovered lifecycles |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info` | FAIL, exit 1, daemon unreachable |

An executed inline `uv run python` probe loaded `run_soak.py` with `runpy` and
asserted that both `sustain_duration` and `exact_rc_artifact` fail for the four
frozen historical packs: `m3a-soak-evidence.json`, `m3a-repair-validation.json`,
`m3a-round5-final.json`, `m3a-round6-shakedown.json`. All assertions passed.
The final two packs report 90.17 and 90.43 seconds, not the required 14400.
Raw evidence was preserved unchanged.

The executed production-middleware regression demonstrates the same authenticated
or unauthenticated identity receiving `[200, 200, 429]` from each independent
replica instance. Exhausting one does not exhaust the other. This is a meaningful
counterexample to shared allowance, but an ASGI test is not a live RC soak.
Task-admission regression traverses the real router/queue/Run store and checks
429 plus Retry-After at a full ceiling and admission after a slot frees. The
schema-lock regression checks SQL ordering with a fake connection, not a live
PostgreSQL race. The sampler regression observes an actual child process, not
long-window application leaks. Boot-contract tests validate configuration, not
a running deployment. None of these results substitutes for missing load evidence.

## Acceptance disposition

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC profile | PARTIAL: existing profile names mix/thresholds but explicitly omits concurrent users/Workspaces, fan-out, successful tools/models, Canvas/Design and Goal/background workload justification. Representative coverage UNVERIFIED. |
| Two application replicas | Configuration tests pass; two live exact-RC replicas UNVERIFIED. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks and shutdown | UNVERIFIED: historical packs fail the executed duration/artifact gates; no new live load. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: the documented schedule probe admits then cancels its queued Run; admission uniqueness does not prove physical-work uniqueness. |
| Non-bypass rate/security/degraded behavior | NOT MET for a shared allowance: executed production middleware tests demonstrate independent replica budgets. Sustained security/degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | PARTIAL: documented profile and sampler regressions exist; application event-loop, worker, pool/locks, queue, error/timeout and long-window resource observations UNVERIFIED. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED: historical process exit/rejoin does not prove physical Attempt loss/duplication outcomes. |
| Long-running exact RC artifact/configuration | NOT MET: no selected immutable RC artifact/config supplied; Docker unavailable; current harness is explicitly preflight-only; all four historical packs fail promotion. |
| Earliest-invariant finding filing/reclassification | PARTIAL: existing local finding records reviewed; external filing UNVERIFIED. No GitHub mutations permitted/performed. |
| Human/machine evidence tied to exact hashes | PARTIAL: historical documents/JSON exist; promotion-eligible artifact/config-bound evidence UNVERIFIED. |

## Committed handoff

Verdict: **BLOCKED**. Only changed file is this report. No tests added, hence no
inventory delta; no source, runtime config, ledger, grant or historical evidence
edited. The CI-ledger assessment is complete with no findings to repair. Do not
repeat unchanged scanner validation expecting it to produce a justified patch.

Next prerequisites: working Docker cell, selected immutable RC images and
normalized production configuration/provider setup. Then complete missing
representative production workloads, physical-work recovery oracles and telemetry;
resolve the replica-budget acceptance mismatch; execute a >=14400-second soak
of that frozen artifact/configuration. Any code/runtime-config change requires a
new soak. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and canonical
store-owned fencing. No push, GitHub mutation or destructive git command.

Progress: checked 1, done 0, skipped 0, errors 1 (Docker prerequisite).
This local commit checkpoints validation and unresolved acceptance, not integration
approval.
