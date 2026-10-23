# Issue #860 — repair validation, job 21115d90

## Frozen scope

- One item: issue #860, branch `auto-860` in the assigned worktree.
- Starting head: `14482ea3a6c401f355adba56a8cc1b0f345607dc`.
- Supplied develop base: `11376c7bef4ea7d17195b90bea8ca9a64a769bb1`.
- Initial status: clean; no incoming uncommitted work to salvage.
- Inputs: supplied dispatch-context.json and prior result c1f40c2f; no GitHub mutations or refreshed issue/PR lists.
- Inspection snapshot: repository instructions; relevant execution, lease, recurrence,
  deployment, rate-limiting and measurement ADRs; `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`,
  production rate-limit/task and pg_learnings code and adjacent tests;
  `docs/testing/soak/m3a-load-profile.md`, round6 evidence and prior repair report;
  quality-gate documentation, vulture checker/ledger and CI invocation.
- Edit scope: this report; only scanner-demonstrated issue-related dead code or
  reviewed retained identities in `quality/vulture-baseline.json` if necessary.
  Test changes, if needed, require an inventory note.

## Assumptions and initial evidence

This is the writer repair lane. The explicit vulture CI-repair exception permits
ledger amendment only for observed findings, not speculative changes. Full release
acceptance remains separate from deterministic harness validation. No `check-*.log`
files were present in the supplied job directory at the initial snapshot.

## Results

- Exact requested vulture command passed: 1,336 reviewed identities and 1,336
  findings; zero unclassified/never-allowlist findings. No ledger amendment is
  warranted. The checker selected provenance base `56332162cf63`.
- `uv run ruff check .` passed.
- `uv run ruff format --check .` passed (3,003 files).
- `git diff --check 11376c7bef4ea7d17195b90bea8ca9a64a769bb1...HEAD`
  passed; the historical blank-EOF finding is not reproducible at this head.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: **83 tests**, 2.64 seconds. Includes actual production middleware
  instances showing independent allowances for both identity classes, not merely
  a mocked rate-limit verdict.
- `uv run python scripts/check-suite-inventory.py` passed: 15 suites,
  27,048 unique identities, no duplicate evidence.
- These validations used 1,200-second tool timeouts. They establish regression
  coverage, not a deployed multi-replica RC soak.

## Architecture and acceptance boundary

Read accepted ADR-081426-1f7c (runtime mechanics), ADR-081626-f383 (Attempt
fencing), ADR-082126-f69c (recurrence produces Runs), ADR-085 (principal rate
limits), ADR-083026-a91e (unmeasured metrics), and proposed ADR-081 (deployment).
No alternate scheduler, execution authority, Goal store, event authority or
principal resolver is introduced. Admission identity counts cannot prove
physical Attempt uniqueness; driver-loop latency cannot stand in for application
loop measurements. Process-local #842 enforcement is not #860's stronger
replica-selection non-bypass guarantee. These differences are blockers, not
waivers or reasons to weaken the acceptance gates.

## Additional executed checks

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  — 34 passed, 6 skipped (1.44 seconds). Skipped cases are not acceptance proof;
  no live PostgreSQL concurrency claim is made from this run.
- `uv run python -` imported the actual soak driver and evaluated retained round6
  JSON, asserting both `sustain_duration` and `exact_rc_artifact` fail. Output:
  90.43 observed seconds versus 14,400 required, evidence commit
  `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, and current preflight artifact
  `{ok: false, topology: host-uvicorn-preflight}`. This is freshly executed
  rejection evidence, not a fresh soak.
- `uv run python scripts/check-doc-links.py` — passed, 1,858 Markdown files,
  zero broken relative links.

## Acceptance audit

| #860 criterion | Evidence and disposition |
| --- | --- |
| Representative users/Workspaces, Graph fan-out, schedules, queue, tool/model, Design/Canvas and worker profile | **UNVERIFIED**. `m3a-load-profile.md:152-165` explicitly records missing population/workloads/telemetry. A single-key degraded model path is not the whole supported profile. |
| At least two application replicas | **UNVERIFIED for deployed RC**. `deploy/docker-compose.prod.yml:26-76` declares two replicas; executed static/ASGI tests do not boot the production images. |
| Sustained pool/queue/reclaim/retry/leak and restart observations | **UNVERIFIED**. Current evaluator rejects the retained 90.43-second shakedown (`evidence/m3a-round6-shakedown.json:165,221-224`). No fresh long run executed. |
| No duplicated physical schedule/task/Run/Attempt work and Goal reconciliation | **UNVERIFIED**. `m3a-load-profile.md:197-200` says the schedule probe Run is cancelled without execution; admission deduplication alone does not demonstrate physical fencing. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Counterexample reproduced** by `test_replica_selection_has_an_independent_production_allowance`, both identity classes: each replica returns `[200,200,429]`. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:628`; local state is constructed at `api/rate_limit.py:72-77`. Remaining concurrent security/degraded guarantees are **UNVERIFIED**. |
| Complete PostgreSQL/application-loop/worker/RSS/FD/queue/error telemetry with thresholds | **UNVERIFIED**. Profile lines 157-165 distinguish process-group sampling and driver lag from application/worker evidence. Unit sampler tests are not sustained application measurements. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED**. No new deployed fault injection; process rejoin and terminal Run counts alone cannot prove absence of lost or duplicate physical work. |
| Long soak of exact promoted artifact/configuration | **NOT MET by available evidence**. Executed artifact check rejects host uvicorn (`scripts/soak/run_soak.py:635-646`), and the retained run fails duration. No immutable RC selection supplied. |
| Findings filed/reclassified at earliest broken invariant | **UNVERIFIED as a complete claim**. Historical findings are retained, but no fresh load run occurred; external issue mutations are prohibited. |
| Machine/human evidence bound to exact promoted hashes | **UNVERIFIED**. Retained evidence names an older head at `evidence/m3a-round6-shakedown.json:70`, not the assigned commit; no current production image/config identity proof. |

## Disposition and next prerequisite

**BLOCKED** for issue acceptance. No scanner-demonstrated defect required code or
ledger changes; changing the ledger would invent a repair. Prior whitespace
failures were not reproduced. The previous acceptance block remains substantive:
select the immutable production RC/configuration, supply representative canonical
workloads and application telemetry, address replica-selection enforcement in its
existing canonical path, then execute a qualifying four-hour fault-injection soak
with physical Attempt correlation. Another emulator shakedown cannot satisfy it.

Only this handoff report changed; no tests were added or removed, so no inventory
note is needed. Existing implementation/evidence is preserved. No gate, ledger,
grant, runtime configuration or GitHub state changed. Validation output is in
this job's tool transcript; there were no driver `check-*.log` files to inspect.

Progress: checked 1, done 0 acceptance-complete, skipped 0 assigned items,
validation-command errors 0. Next: the production-RC prerequisites above, not
another cosmetic CI-repair round. This is a local writer handoff, not integration
approval.
