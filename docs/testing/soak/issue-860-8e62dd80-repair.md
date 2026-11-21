# Issue #860 repair validation — 8e62dd80

## Frozen scope and initial state

Only issue #860 in assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, clean starting HEAD `cb259059670f79239c889268a08a8075631ef774`.
Supplied base: `435dc1937e0407ab4de198ffcced49860bb14ad2` (resolved by diff).
No uncommitted work, conflict, or reason to sync was found.

Offline inputs: current job dispatch-context.json, prior result 8726af2b,
and failed `98a11313/check-3.log`. Current job contained no check logs at
initial snapshot. No GitHub mutations or campaign re-enumeration.

Frozen candidate edit paths: this report, learnings schema implementation and
its persistence tests, `quality/vulture-baseline.json` only if the prescribed
scan identifies actual retained debt, and an inventory note only if tests
change. Soak harness/profile/tests and relevant ADRs are read-only evidence.
Assumption: writer role applies; release artifact designation cannot be
inferred from a source branch or earlier host preflight evidence.

The supplied failure expected 21 schema statements but observed 24. This
will be reproduced before proposing a repair. Earlier PASS/BLOCKED claims
are not treated as fresh validation. The inherited diff is preserved.

## Fresh results

- Prescribed vulture scan: PASS, 1323 reviewed identities / 1323 findings,
  zero unclassified or forbidden findings; selected base `4aa68edc0b6b`.
  `/tmp/860-8e62dd80-vulture.log`. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **103 passed, 6 skipped**, 2.52 seconds, `/tmp/860-8e62dd80-tests.log`.
  The supplied schema failure does not reproduce. The existing independent
  expected list already includes the three validation audit columns at lines
  174–176. Database skips are not multi-replica database evidence.

Both commands ran with 1200-second timeouts. No production or test edit is
supported by these results; no inventory-count delta exists.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified
  lifecycles. These four logs are `/tmp/860-8e62dd80-{ruff,format,deployment,lifecycles}.log`;
  commands ran with a 1200-second timeout.
- Verified the vulture arguments against `.github/workflows/quality.yml:1078`
  and `vulture-ratchet.yml:82`; no gate or grant was modified.

## Reachable behavior and ADR reconciliation

Read `AGENTS.md`, documentation authority map, ADR-081 (Proposed), ADR-085,
ADR-081426-1f7c and ADR-082526-b36a (Accepted). Proposed deployment guidance
cannot waive acceptance. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`:
physical execution identity is Attempt, and multi-worker recovery must follow
lease expiry/renewal and fencing, not restart-implies-death. Admission receipt
uniqueness alone is therefore not physical-work uniqueness.

`maistro_server/main.py:648` installs the production rate middleware;
`api/rate_limit.py:95` constructs process-local state. The freshly executed
`tests/test_soak_promotion_gates.py:439` exercises that actual middleware on two
instances with the same principal/IP: each independently returns `[200,200,429]`.
This falsifies a shared allowance interpretation of replica-selection non-bypass,
not local enforcement. ADR-085 specifies principal identity but does not settle
shared storage; #842's documented process-local semantics are not an accepted
waiver of #860's stronger wording. That ambiguity remains UNRESOLVED; do not
invent a parallel authorization path or change the rate-budget contract here.

The backpressure test executes the real task router and canonical in-memory
Run spine: full ceiling -> 429/Retry-After, another principal -> admitted,
released slot -> admitted. Production translation is `api/tasks.py:117`.
This is meaningful boundary evidence, not a multi-replica PostgreSQL soak.
The sampler test observes actual uv child RSS/fd growth. Other harness tests
use mock HTTP responses and synthetic evidence; they prove fail-closed probe
logic, not live RC behavior.

## All ten acceptance criteria

| Criterion | Fresh evidence / status |
| --- | --- |
| Representative release workload | **UNVERIFIED**. Profile exists, but `m3a-load-profile.md:152` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful models/tools, Design/Canvas and Goal/background workloads. RC applicability not established. |
| Two deployed application replicas | **UNVERIFIED**. Two middleware instances in ASGI tests are not two deployed RC replicas. |
| Sustained saturation, growth, reclaim, retry, leaks and shutdown | **UNVERIFIED**. Real sampler test passes; no sustained RC execution occurred. |
| No duplicate physical work across replicas | **UNVERIFIED**. Receipt-probe regression passes but does not observe physical Attempt effects or sustained Goal reconciliation. |
| Rate/security/degraded non-bypass | Shared allowance interpretation falsified by real middleware test above; local enforcement and admission backpressure pass. Full production security criterion **UNVERIFIED**. |
| Complete metrics with thresholds | **UNVERIFIED at RC grade**. Profile has thresholds, but driver event-loop lag is not application event-loop lag; no fresh sustained pool/lease/worker telemetry. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**. Boot-cleanup tests pass, not evidence of physical-work recovery. |
| Long-running exact RC/configuration | **UNVERIFIED / BLOCKED**. `scripts/soak/run_soak.py:730` always rejects host preflight as exact artifact. Executed CLI regressions reject even synthetic four-hour preflight evidence. No immutable RC/config designation established by supplied parent #89 body. |
| Findings filed/reclassified before promotion | Local classification recorded here: rate allowance ambiguity is a security contract prerequisite, missing Attempt evidence is a canonical execution/recovery prerequisite. External filing/reclassification **UNVERIFIED**; GitHub writes prohibited. |
| Machine/human evidence tied to exact artifact/config hashes | **UNVERIFIED for RC**. This handoff binds fresh tests to the starting source HEAD, not a promoted image/config or long soak. |

## Disposition

**BLOCKED**, not a reproduced CI-ledger failure or develop-sync conflict. Only
this report changed; production, tests, inventory and ledger remain unchanged.
No evidence-backed code repair is warranted in this round. Existing work is
preserved. Commit this handoff locally; it is not integration approval.

Required next input: designate immutable RC artifact and runtime configuration,
justify representative workload coverage, and resolve replica-selection budget
semantics. Then execute production-topology long soak with physical Attempt
effect correlation, complete telemetry, and active-work crash/drain recovery.
Repeated schema/vulture repair dispatches cannot satisfy those prerequisites.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0;
errors 0 fresh validation commands; next: release designation and production soak.
