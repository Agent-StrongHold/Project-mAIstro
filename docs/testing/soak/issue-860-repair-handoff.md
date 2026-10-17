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

---

# Current repair round — starting HEAD `7a52345ba731`

## Frozen scope

- Issue: #860 only; writer lane `auto-860`.
- Starting HEAD: `7a52345ba73163fe9ecd4a58c9fe7caf5c92355f`; supplied develop base: `4df9dd9bde4c6d03fccd1466cf9d6827a8fd4aa8`.
- Starting worktree clean; no salvage patch needed.
- Repair targets: `docs/testing/soak/m3a-soak-evidence.md`, this handoff, and (only for reviewed findings of the requested CI gate) `quality/vulture-baseline.json`.
- Validation inputs: existing soak profile/evidence/harness/tests, relevant ADRs and deployment/rate-limit implementation, vulture checker and ledger.
- No driver `check-*.log` files present in the supplied job directory at initial inspection.

## Assumptions and limits

This is a writer repair, not verifier-only execution. Existing preflight evidence cannot establish a four-hour soak of the exact production RC artifact. No GitHub mutation or new issue filing is authorized. Missing production proof must remain explicitly unverified; no scheduler, execution authority, or cluster-wide limiter will be invented in this lane.

## Progress

- Confirmed exact assigned HEAD and clean worktree.
- Requested vulture gate passed: 1,371 findings / 1,371 reviewed identities, zero unclassified and zero never-allowlist findings. No ledger amendment is justified.
- Prior result artifact reports BLOCKED at the current starting HEAD. Inspection confirms the historical H3 shared-store assertion has already been corrected: current evidence explicitly states process-local allowances and unmet replica-selection acceptance. No speculative repair to that text is warranted.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (2,720 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: 80 passed, 5 skipped in 23.43 seconds. PostgreSQL integration skips explicitly require `MAISTRO_TEST_PG_DSN`; no live database concurrency proof is claimed.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified/discovered lifecycles.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Re-read accepted runtime, execution-fencing and rate-limit ADRs plus proposed deployment ADR. Reconciliation unchanged: Attempt identifies physical execution; lease expiry is not automatic takeover authority; per-principal limits do not imply a shared store. No new execution/authorization authority is introduced.
- Existing tests were inspected and rerun, not added or changed; no inventory delta is required. Historical handoff above is preserved, with this round appended.
- Executed an `uv run python` import of the current harness and reevaluated the four fixed historical evidence paths with `failed_promotion_checks`: run 1 and repair validation each fail seven gates; round 5 fails rate enforcement, duration and exact artifact; round 6 fails duration and exact artifact (90.43 seconds versus 14,400 required). All four fail duration and exact artifact. This checks summary flags, not physical execution traces.
- `git diff --check`: PASS. An executed byte-for-byte prefix assertion confirms the previous committed handoff is preserved, with only this round appended.

## Current acceptance disposition and handoff

The ten-criterion table above remains the disposition after this round's independent inspection and execution, not a reliance on prior green claims. The production middleware tests again demonstrate replica-local allowances for both authenticated and unauthenticated identities. The live subprocess sampler regression passed; that is not application telemetry under RC load. The reference Compose declares two replicas but does not designate immutable promotion images/configuration. No production RC deployment or four-hour soak was executed. Representative traffic coverage, physical-work deduplication/Goal reconciliation, full telemetry, saturation/reclaim/leak observations and active-work recovery remain UNVERIFIED. Local finding classifications and historical hash-tied evidence remain preserved; external filing is UNVERIFIED and prohibited in this lane.

**Verdict: BLOCKED.** The requested CI gate is already green and the prior documentation contradiction already repaired. There is no evidence-backed code or ledger repair to make. Completion needs a designated immutable RC/configuration, resolution of the replica-selection rate-limit mismatch, a production-topology workload/telemetry runner and a qualifying soak; a longer host-process preflight cannot supply that proof. No ledger, production, harness, test or inventory files changed. Only this handoff changed.

Progress: checked 1, done 0 (issue acceptance incomplete), skipped 0 issues, errors 0 validation commands; 5 explicitly skipped PostgreSQL test cases. Next: promotion owner supplies RC artifact/configuration and resolves remaining acceptance prerequisites. This checkpoint is committed locally, not integration approval.

---

# Issue #860 focused repair checkpoint — job `a66a3b10`


Snapshot: issue #860 only, branch `auto-860`, starting HEAD
`5aa88c8a8c0c5c11ce4bbe7f815cb74e3cc9b4e7`, assigned base
`8c8fc8d6706a0837bd991c4e92138bf4d776ac9e`. Initial worktree clean.

Frozen scope: inspect the existing soak profile/evidence, production limiter,
soak promotion tests, relevant ADRs, vulture checker and CI arguments; repair
only evidenced #860 documentation or vulture identities in
`quality/vulture-baseline.json` and directly implicated source. No deployment
or release approval is implied. No remote mutations.

Assumption: this is the writer/CI-repair role. The assigned job directory
contained no `check-*.log` files at initial inspection; earlier green claims
will not be treated as current validation. The exact RC artifact/configuration
has not been supplied. A short host-based preflight cannot satisfy a four-hour
production-artifact soak. Missing acceptance evidence will remain explicit.

Progress: confirmed assigned HEAD and clean worktree; repository instructions
read. Exact CI vulture command passed: 1361 findings / 1361 reviewed identities,
zero unclassified or forbidden findings, base `8c8fc8d6706a`. No unbanked
identity exists to repair and no ledger amendment is justified. Reviewed the
previous result artifact (BLOCKED) and current profile/evidence: earlier H3
shared-store overclaim is already corrected; exact-RC, duration and physical
execution acceptance gaps are still explicitly documented. Additional focused
validation: focused pytest completed (80 passed, 5 skipped; live PostgreSQL
cases require `MAISTRO_TEST_PG_DSN`). Docker check independently failed:
`DOCKER_HOST=unix:///var/run/docker.sock timeout 90 docker info` returned 1,
Cannot connect to the Docker daemon. No production soak can run in this
current environment. Earlier handoff content is preserved above.

## Current executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS (1361/1361), matching `.github/workflows/quality.yml:962`.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`: 80 passed, 5 skipped in 2.82s. Skips need a migrated PostgreSQL DSN; no live database claim.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS, 2802 files.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19/19 classified lifecycles.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `uv run python` imported the current harness and checked the four fixed historical JSON packs: all rejected on `sustain_duration` and `exact_rc_artifact`. This evaluates recorded summaries, not raw execution traces.
- Executed byte-prefix assertion: historical handoff preserved exactly. Initial `git diff --check` found an extra EOF blank line in this appended section; removed before commit.

Accepted ADR-081426-1f7c identifies physical execution by Attempt; accepted
ADR-081626-f383 explicitly does not grant lease-expiry takeover authority.
ADR-081 remains Proposed. Reconciliation: preserve the canonical execution
spine and do not reinterpret admission deduplication as physical-work fencing
or invent reclaim authority to satisfy the soak request.

## Acceptance — current independent disposition

| Criterion | Evidence / disposition |
|---|---|
| Representative release profile | PARTIAL: profile inspected; its remaining-gaps section explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and sustained Goal/background-worker traffic. RC applicability UNVERIFIED. |
| Two application replicas | UNVERIFIED for exact RC: Docker daemon unreachable; no deployment executed. |
| Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: all four historical packs rejected by current duration/artifact gates. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission probes do not establish physical Attempt uniqueness; no new live workload. |
| Security/degraded behavior and replica-selection non-bypass | NOT MET for aggregate rate allowance: executed production middleware tests grant the same identity another allowance on replica 2. Security/degraded behavior under exact-RC load UNVERIFIED. |
| Complete telemetry with explicit thresholds | PARTIAL: live subprocess resource regression passes; RC PostgreSQL, application-loop, worker counts, queue and error/timeout threshold observations UNVERIFIED. |
| Kill/restart during active work with fencing/recovery | UNVERIFIED: no active RC work or restart performed. |
| Long-running exact-RC soak | BLOCKED: no designated immutable RC/configuration; Docker unavailable; host driver always rejects artifact equivalence. No four-hour run executed. |
| Findings filed/reclassified | Existing local earliest-invariant classifications reviewed; external filing UNVERIFIED and prohibited in this lane. |
| Hash-bound machine/human evidence | Historical preflight evidence preserved, not promoted; qualifying exact-RC evidence UNVERIFIED. |

Verdict: **BLOCKED**. Only this handoff changes. No production, harness, ledger,
grant or test changes; no inventory delta is needed. The prior H3 overclaim is
already corrected, and the requested vulture repair has no failing identities.
This is a committed validation checkpoint, not completion or promotion approval.

Progress: checked 1, done 0, skipped 0 issues; 1 environment failure (Docker),
5 explicitly skipped PostgreSQL tests. Next: provide reachable deployment
infrastructure and designated immutable RC/configuration, resolve the aggregate
rate-limit acceptance mismatch, and run a production-topology workload with
physical Attempt correlation and complete metrics for at least four hours.

---

# Issue #860 CI repair checkpoint

## Frozen scope

- Assigned issue only: #860, branch `auto-860`, starting HEAD
  `c5f6519ed7cc31d802fb664d1963bdc048df36a2`, supplied develop base
  `b35c76e035b3ee60789f9eac3e82526e23aba2e1`.
- Worktree `/home/dev/Git/wt/auto-860` was clean at entry. No salvage required.
- Process the explicit vulture exact-debt-ledger repair and verify existing soak
  acceptance evidence; no new production concurrency architecture or invented RC.
- Candidate edit scope: reviewed findings in `quality/vulture-baseline.json`,
  genuinely dead code identified by the requested scan, existing soak documentation,
  this handoff; any necessary regression tests require inventory notes.
- Job directory contains no `check-*.log` files at initial inspection. Driver
  validation claims are not accepted as evidence.
- Ambiguity: assignment is a writer/repair lane despite generic verifier text.
  Proceed as writer, perform local validation, and commit locally. A missing
  four-hour exact-RC soak remains a release blocker, not something a ledger repair
  can certify.

## Progress

Entry state verified; repository instructions read. Validation pending.

Requested vulture gate independently passed: 1,345 findings / 1,345 reviewed
identities, zero unclassified and zero forbidden findings. No ledger edit is
justified. Prior H3 overclaim is already corrected in current evidence.
The existing historical handoff was recovered byte-for-byte from HEAD after
an initial filename collision; all earlier content is preserved above.

Focused pytest (the two changed-package modules plus soak promotion and production
boot-contract tests) passed: **88 passed, 5 skipped** in 3.20s. All five skips
require `MAISTRO_TEST_PG_DSN`; they are not live PostgreSQL evidence. Ruff check
passed and format check passed (2,859 files). Existing production-middleware
regressions reproduce independent allowances for the same identity on both
replicas; sampler tests observe a real subprocess, not production RC telemetry.
No tests were added or changed, so no inventory delta is required.

Reviewed accepted runtime/fencing/rate-limit ADRs and proposed deployment ADR.
Attempt remains the physical identity; accepted fencing explicitly does not grant
lease-expiry takeover authority. No alternative scheduler, store or authorization
path is introduced. The reference Compose has two services but mutable images
and a local application build, not a designated immutable promotion RC.

## Current validation and acceptance disposition

Commands executed this round:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,345 reviewed identities/findings. No unbanked identity to repair; ledger unchanged.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2,859 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: 88 passed, 5 skipped (missing migrated PostgreSQL DSN).
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19/19 classified.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `uv run python` imported the current harness and reevaluated the four fixed historical JSON evidence packs: all rejected on duration and exact artifact; round 5 records 90.17 seconds and round 6 records 90.43 seconds. This checks summary flags, not raw physical-work traces.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 90 docker info --format '{{.ServerVersion}}'`: PASS, server 29.7.2. Earlier rounds' Docker-unavailable finding does **not** apply to this round. No services were started or stopped.

| Acceptance criterion | Current evidence / remaining gap |
|---|---|
| Representative RC workload | Profile inspected; multi-user/Workspace, fan-out, successful tools/models, Design/Canvas and background workload applicability remains UNVERIFIED. |
| Two application replicas | Compose defines two; boot-contract tests pass. Two deployed exact-RC replicas UNVERIFIED. |
| Sustained saturation/reclaim/backoff/leaks | All four historical packs fail duration/artifact gates; long-window behavior UNVERIFIED. |
| Exactly-once/fenced physical work and Goal reconciliation | Admission-oracle regressions pass, but physical Attempt uniqueness and sustained Goal reconciliation UNVERIFIED. |
| Rate/security/degraded concurrency, replica non-bypass | Executed real middleware regression reproduces another allowance after replica selection for both identity classes; aggregate non-bypass unmet. Exact-RC security/degraded load UNVERIFIED. |
| Complete metrics and thresholds | Live subprocess sampler regression passes; full RC database/application-loop/worker/queue/error/timeout observations UNVERIFIED. |
| Kill/restart during active work | Physical fencing/recovery/loss prevention UNVERIFIED; no new deployed restart. |
| Long-running exact RC/configuration | No designated immutable RC and no qualifying four-hour soak. Host driver always rejects exact artifact; UNVERIFIED. |
| Findings filed/reclassified | Local M3-A evidence-validity classifications inspected; external filing UNVERIFIED and prohibited in this lane. |
| Hash-bound machine/human soak evidence | Historical preflight evidence preserved and rejected for promotion; qualifying RC evidence UNVERIFIED. |

## Current handoff

**BLOCKED.** No actual failing vulture identity or unrepaired H3 documentation
claim was found. No speculative code, ledger or cosmetic evidence repair made.
Only this checkpoint changes; all prior implementation and historical evidence
remain intact. Docker is reachable, but infrastructure availability alone cannot
supply a designated RC, representative production runner or four-hour evidence.

Next: promotion owner designates immutable artifact/configuration and applicable
workloads, resolves the replica-selection allowance mismatch, supplies a
production-topology runner with physical Attempt correlation and full telemetry,
then performs the qualifying soak on the unchanged RC. No issue closure or remote
mutation performed. This local commit is a validation handoff, not approval.

Progress: checked 1 assigned issue, done 0 (acceptance incomplete), skipped 0
issues, errors 0 validation commands; 5 explicitly skipped PostgreSQL cases.
