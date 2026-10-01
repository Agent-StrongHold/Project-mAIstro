# Issue #860 repair checkpoint

## Frozen scope

- Single assigned item: #860, branch `auto-860`, starting HEAD `1608d0cca8ae4e800b577e960342882ce9e734dd`; supplied develop base `f8cc3597be20f2d46af4063e1a3f74771ab80d05`.
- Worktree verified clean at entry. No salvage patch needed.
- Repair scope: existing soak profile/evidence and adjacent harness/tests; explicitly requested exact-debt-ledger gate (`scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json`) and only identities it reports. No other issues, scheduler, authorization or execution authority changes.
- Job directory has no `check-*.log` files at entry; driver verification is unavailable, not assumed green.
- Assumption: this is a writer repair round. Inspect existing evidence, run gates directly, document promotion blockers rather than represent preflight as an exact-RC soak.

## Progress

Repository instructions and prior result read. Prior repair ended BLOCKED at the exact assigned starting HEAD, citing no designated exact RC/configuration and no qualifying four-hour soak. This is not a develop-sync conflict.

Executed exact requested Vulture command: PASS, 1,402 findings / 1,402 reviewed identities, zero unclassified and zero never-allowlist findings. No dead-code or ledger amendment is justified by this result. Existing prior implementation is retained unchanged. Focused validation completed:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (2,624 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: 80 passed, 5 skipped. All skips require `MAISTRO_TEST_PG_DSN`; this execution does not prove live PostgreSQL concurrency.
- Existing production-middleware regressions confirm a second replica grants another allowance to the same authenticated or unauthenticated identity. Existing CLI regression rejects even synthetic four-hour evidence without exact-RC identity. Existing process-group regression measures real child resource growth. None is a deployed RC soak.

Architecture reviewed: accepted ADR-081426-1f7c makes Attempt the physical execution identity; accepted ADR-081626-f383 explicitly separates stale-writer fencing from lease-expiry takeover. Accepted ADR-085 requires principal-keyed limits but does not establish cluster-shared storage. ADR-081 is Proposed, not an accepted override of the issue. Preserve the canonical Goal -> Graph -> Run -> NodeRun -> Attempt model; do not infer physical-work uniqueness from admission-only counts or invent reclaim authority to meet the load criterion.

Production reference `deploy/docker-compose.prod.yml` defines two application replicas but uses local build and mutable service tags, not a designated immutable RC. Existing host-process harness cannot certify that topology. Prior false shared-limiter claim is already corrected in `m3a-soak-evidence.md`; no further cosmetic patch is warranted.

## Additional executed checks

- Imported `scripts/soak/run_soak.py` with `uv run python` and evaluated the four existing evidence JSON documents through `failed_promotion_checks`, without running or modifying the historical load evidence:
  - `m3a-soak-evidence.json`: seven failed current gates, including duration and artifact identity.
  - `m3a-repair-validation.json`: seven failed current gates, including duration and artifact identity.
  - `m3a-round5-final.json`: rate enforcement, duration and artifact identity fail; observed duration 90.17 seconds.
  - `m3a-round6-shakedown.json`: duration and artifact identity fail; observed duration 90.43 seconds versus 14,400 required.
  - This evaluator checks recorded summary flags, not raw physical execution traces; its rejection is not an independent validation of the other flags.
- `uv run python scripts/check-deployment-claims.py`: PASS (named shipping components exist; not a deployment soak).
- `uv run python scripts/check-suite-inventory.py --help`: inspected invocation.
- `uv run python scripts/check-security-inventory.py --help`: script executed its check rather than printing help; PASS (59 cited paths, 23 inventory rows, two counted claims).
- `uv run python scripts/check-suite-inventory.py --suite tests/ --suite packages/maistro-core/tests --suite packages/maistro-server/tests`: PASS (4,198 / 11,531 / 427 collected tests respectively).
- `uv run python scripts/check-execution-lifecycles.py`: PASS (19 classified/discovered lifecycles).
- `uv run python scripts/check-merge-markers.py`: PASS.

No test cases were added or changed, so no inventory delta is required. Existing inventory notes and historical evidence are preserved. Only this handoff document changes in this round; no production, harness, ledger or grant changes.

## Acceptance disposition (all ten criteria)

| Criterion | Executed evidence / unresolved requirement |
|---|---|
| Representative profile | PARTIAL: inspected profile and production Compose. Profile explicitly lacks multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and Goal/background-worker coverage. Applicability to a selected RC is UNVERIFIED. |
| At least two application replicas | Production reference declares two; historical preflight records two. Execution of two **exact-RC deployed replicas** is UNVERIFIED in this round. |
| Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: current evaluator rejects all four historical evidence documents. Ninety-second runs do not establish long-window behavior; sampler regression is not a soak. |
| Exactly-once/fenced physical work | UNVERIFIED: admission-only probes cancel their schedule Run; no correlated physical Attempt traces or sustained Goal reconciliation proof. Accepted fencing ADR does not itself grant lease-expiry takeover. |
| Security/rate/degraded concurrency and replica non-bypass | NOT MET for cluster-wide principal allowance: executed real middleware regression grants `[200, 200, 429]` independently on each replica for the same identity. Six-path enforcement tests do not prove aggregate non-bypass. Degraded/security RC load behavior remains UNVERIFIED. |
| Complete metrics with thresholds | PARTIAL: process-group regression passes; historical wrapper measurements are invalid for application health. Application-loop latency, worker/cgroup census and complete RC threshold observations remain UNVERIFIED. |
| Active-work kill/restart with fencing/recovery | UNVERIFIED: historical rejoin/drain summaries do not prove in-flight physical-work uniqueness or loss prevention. No new deployment restart performed. |
| Four-hour exact-RC artifact/configuration soak | BLOCKED: no immutable RC/configuration designated in the assignment. Existing host-process driver always rejects exact-RC equivalence. No qualifying run executed; running it longer would not cure topology mismatch. |
| Findings filed/reclassified before promotion | Local earliest-invariant classifications preserved (F11/F12: M3-A evidence validity). External filing remains UNVERIFIED; GitHub mutations are prohibited. |
| Hash-tied machine/human evidence | PARTIAL: historical hash-tied preflight documents inspected and rejected for promotion. Exact-RC image/package/config evidence is UNVERIFIED. |

## Handoff / stop condition

Verdict: **BLOCKED**, not integration approval. CI debt is not the blocker: the exact requested Vulture gate is already green, so adding retained identities or deleting code would be an evidence-free change. Likewise, the prior false H3 statement has already been repaired.

Next owner must designate immutable RC image/configuration and applicable workload surfaces, resolve the aggregate rate-limit acceptance mismatch, implement/use a production-topology runner with physical Attempt correlation and complete application metrics, then execute at least four hours on the unchanged RC and publish hashes plus raw and interpreted evidence. Do not promote the historical shakedown or synthetic regression fixtures to release evidence.

Progress: checked 1 assigned issue; done 0 (acceptance unresolved); skipped 0; errors 0 in executed validation; 5 PostgreSQL integration cases skipped explicitly. This handoff is committed locally as the completed repair-round checkpoint, not completion of #860.
