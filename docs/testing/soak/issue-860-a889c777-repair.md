# Issue #860 repair — a889c777

## Frozen scope

- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `5c4631711ca81cdf3c8fc84552abf904368fb82e`;
  supplied base `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- One item: issue #860, using the supplied dispatch-context.json snapshot only.
- Initial worktree clean; no salvage required. No current-job check logs supplied.
- Inspect the reported prior check-3.log, prior result, relevant ADRs, existing
  soak harness/profile/promotion tests, adjacent production middleware and tests,
  and the vulture checker/workflow. Execute focused validation.
- Edit scope: this report; quality/vulture-baseline.json only if the exact scan
  supplies reviewed retained identities; implicated #860 source/tests/inventory
  only if fresh evidence demonstrates a repair is required.
- Do not promote host smoke results into RC evidence or invent an RC designation.
  Prior BLOCKED verdict is evidence to recheck, not an instruction to manufacture
  acceptance. No remote mutations, broad repairs, or new execution authority.

## Progress

- Exact prescribed vulture scan freshly passed: 1323 reviewed identities and
  1323 findings, zero unclassified/forbidden findings; checker selected base
  `4aa68edc0b6b`. No identity amendment is justified.
- Read supplied failed check-3.log: schema fence expected 21 statements but
  observed 24. Reproduction pending.
- Snapshot parent #89 specifies exact shipping artifacts and real-model soak,
  but its body does not designate an immutable candidate/configuration.
- Existing profile explicitly calls the runner a host-process preflight and
  lists representative-workload and physical-work recovery gaps. No waiver
  inferred from prior results or issue comments.

## Executed validation

All commands used 1200-second tool timeouts on the starting source tree, with
only this report added. Results are fresh, not copied from previous jobs.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323/1323 identities, zero unclassified/forbidden |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q` | 103 passed, 6 skipped, 2.73 seconds |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run python scripts/check-deployment-claims.py` | PASS |
| `uv run python scripts/check-execution-lifecycles.py` | PASS, 19 classified/discovered lifecycles |

Vulture arguments match `.github/workflows/quality.yml:1078` and
`.github/workflows/vulture-ratchet.yml:82`. No ledger/grant edits are warranted.
The reported check-3 failure does not reproduce: the independent expected DDL
list already includes validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:174–176`.
Production `pg_learnings.py:215–216` fences the upgrade transaction with the
advisory lock. Skipped database tests are not live multi-replica proof.

## Architecture and reachable behavior

Read repository instructions, documentation authority map, ADR-081 (Proposed),
ADR-085, ADR-081426-1f7c and ADR-082526-b36a (Accepted). The canonical spine stays
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Physical execution identity is an
Attempt, not an admission receipt. Recovery requires lease renewal/expiry and
fencing, not an assumption that a restarting worker proves all work dead.
Proposed deployment guidance cannot waive exact-RC acceptance.

Production installs `RateLimitMiddleware` at `maistro_server/main.py:648`;
`api/rate_limit.py:95` creates process-local limiter state. Freshly executed
`tests/test_soak_promotion_gates.py:439` uses two actual middleware instances
and proves the same principal/IP gets `[200,200,429]` independently on each.
This falsifies a shared allowance interpretation of replica-selection
non-bypass. ADR-085 requires per-principal identity but does not specify a
shared store. Ambiguity remains UNRESOLVED: assume existing #842 process-local
semantics are intentional, but not a waiver of #860's stronger acceptance.
Do not invent another authorization mechanism in this repair.

The real task-router/backpressure test passes through the canonical in-memory
spine: full ceiling returns 429/Retry-After, another principal remains admissible,
and freeing a slot allows retry. Production translation is `api/tasks.py:117`.
This is a meaningful boundary test, not a database-backed soak. The sampler
regression measures a real uv child's memory/descriptors. Mocked HTTP receipt
and synthetic four-hour evidence tests prove harness rejection logic, not RC
runtime correctness. `scripts/soak/run_soak.py:730` explicitly rejects the host
preflight as exact RC regardless of duration.

## Acceptance accounting

| #860 criterion | Evidence and status |
| --- | --- |
| Representative release workload | **UNVERIFIED**. `m3a-load-profile.md:152` lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads; applicability to a designated RC is not established. |
| At least two deployed replicas | **UNVERIFIED**. Two in-process middleware instances are not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks and shutdown | **UNVERIFIED**. Sampler regression passes, but no sustained RC run was executed. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**. Receipt checks pass; they do not observe physical Attempt effects or sustained Goal reconciliation. |
| Rate/security/degraded non-bypass | Shared allowance interpretation is falsified by the executed production middleware regression; local enforcement and backpressure pass. Full criterion **UNVERIFIED**, not waived. |
| Complete PostgreSQL/application/resource/error telemetry with thresholds | **UNVERIFIED at RC grade**. Existing profile thresholds and driver-loop sampler are not sustained application-loop/pool/lease observations. |
| Active-work kill/restart, graceful drain, fencing/recovery | **UNVERIFIED**. Boot cleanup tests do not prove active physical-work recovery. |
| Long-running exact RC/configuration | **UNVERIFIED / BLOCKED**. No designated immutable RC/configuration established; executable preflight guard rejects even synthetic four-hour evidence. |
| Findings filed/reclassified before promotion | Local classification: rate-budget semantics are a security contract prerequisite; physical-work/recovery evidence is a canonical execution prerequisite. External filing **UNVERIFIED**, remote mutations prohibited. |
| Machine/human hash-bound RC evidence | **UNVERIFIED**. This report binds tests to source HEAD, not an RC image/configuration or sustained run. |

## Handoff

**BLOCKED**. No reproduced code/ledger failure, merge conflict, or evidence-backed
repair justifies changing production/tests. Only this report changed; inventory
counts unchanged, so no inventory-delta note is needed. Preserve all inherited
work and commit this report locally. No integration or promotion approval.

Required next input: release owner designates the immutable RC/configuration and
resolves replica-selection allowance semantics. Complete representative workload
coverage and execute the production-topology long soak, correlating physical
Attempt effects with lease/fencing recovery and complete telemetry. Repeating the
same schema/vulture repair cannot provide those missing release prerequisites.

Progress: checked 1, acceptance-complete 0, skipped 0, fresh validation errors 0;
next: designated RC and production soak. No GitHub mutations performed.
