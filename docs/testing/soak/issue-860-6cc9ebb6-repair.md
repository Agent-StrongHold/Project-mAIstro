# Issue #860 — current-head CI repair review

## Frozen scope and observed blocker

Writer lane `auto-860`, job `6cc9ebb603b74bab8f39cdcf6c68ef90`.
Verified starting HEAD: `457927ca441ca36368541f297127b82e187f0fd2`;
assigned base: `e3233939343b43249aa65a32b6d3b3aeb35d4dc5`.
The worktree was clean. No conflict or incoming changes required salvage.
Scope is issue #860 only: the supplied dispatch snapshot, prior result and
reported check-3 failure, soak runner/profile/tests, production schema and
admission/rate-limit seams, and relevant deterministic gates. No GitHub mutation.

The current job directory contained no driver `check-*.log` files at initial
snapshot. The supplied historical failure at
`98a11313167b41a98a420abfda80c292/check-3.log` is a schema-fence assertion
(24 statements versus 21), not a vulture finding. The current schema test already
includes all three validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`.
Fresh test execution is recorded below rather than presumed from earlier reports.

The required exact vulture scan passed: 1,328 findings, all reviewed;
zero unclassified and zero never-allowlist findings. No retained unbanked or
eliminated identity exists to amend. Ledger/grant edits would be speculative.
The scan reports its provenance base as `28614700bd9a`, distinct from the
assigned develop base; this report does not claim an explicit assigned-base
ratchet comparison.

The lane supplies no immutable promotable image/configuration selection.
Assumption: do not invent an RC or treat host-process smoke traffic as one.
The current runner explicitly fails its exact-artifact gate, and the profile
lists missing representative workloads. This is a release-evidence prerequisite,
not a reason to introduce a new execution authority or weaken gates.

## Architecture reconciliation

Read repository instructions and accepted ADR-081426-1f7c (runtime mechanics),
ADR-081626-f383 (lease fencing), ADR-085 (per-principal rate limits), and
ADR-083026-a91e (unmeasured metrics are absent).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Authoritative Attempt
fencing does not by itself prove exactly-once external effects. Receipt identity
and process rejoin are not physical-work oracles. Driver loop lag is not
application loop lag. Local limiter enforcement is not a shared principal budget.
No production behavior, policy or architectural contract is changed this round.

## Validation

All commands below executed in the assigned worktree, with 1,200-second
validation timeouts. Logs live in
`/home/dev/maistro/jobs/6cc9ebb603b74bab8f39cdcf6c68ef90/`.

| Command | Actual outcome | Log |
| --- | --- | --- |
| `uv sync --locked --extra dev` | PASS | `worker-sync.log` |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,328 reviewed findings, 0 unclassified | `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; historical failure does not reproduce | `worker-schema.log` |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 108 passed | `worker-focused.log` |
| `uv run ruff check .` | PASS | `worker-ruff.log` |
| `uv run ruff format --check .` | PASS; 3,151 files | `worker-format.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS; 17 suites, 28,959 unique identities, no duplicate evidence | `worker-inventory.log` |
| `uv run python scripts/check-merge-markers.py` | PASS | `worker-markers.log` |
| `uv run python scripts/check-ratchet-provenance.py` | PASS; 50 consumers; existing ledgered contract gaps are not behavioral proof | `worker-provenance.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS | `worker-surfaces.log` |
| `uv run python -` importing the current soak evaluator and checking round-30 evidence | PASS: asserted duration below minimum, duration/artifact rejection, and current preflight artifact result false | `worker-artifact.log` |

Workflow arguments were inspected in `.github/workflows/ci.yml`,
`quality.yml`, and `vulture-ratchet.yml`. No full-tree pytest execution,
new live production soak, or skipped PostgreSQL test coverage is claimed.

## Acceptance disposition

| #860 criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `m3a-load-profile.md:153-172` lists missing multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/worker traffic. The selected RC scope needed to justify omissions is absent. |
| At least two production replicas | **UNVERIFIED live.** `scripts/soak/run_soak.py:320-339` starts host uvicorn, not immutable production images. Two ASGI limiter instances in passing tests do not establish deployment behavior. |
| Sustained saturation, queue/reclaim/retry and leak/shutdown observations | **UNVERIFIED.** Sampler tests include real wrapper/child resource growth and missing-measurement cases, but are not sustained application load. Evaluated historical duration is 420.08 seconds versus 14,400 required. |
| No duplicate physical work for schedules/admission/Attempts/Goal reconciliation | **UNVERIFIED.** HTTP receipt tests reject empty, conflicting and duplicate identities; they do not observe physical side effects. `run_soak.py:1044-1072` cancels the probe Run without executing its work. |
| Concurrent security/degradation without replica-selection bypass | **NOT PROVEN.** Executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated identities: both instances independently return `[200, 200, 429]`. Production installs that middleware at `main.py:648`; `api/rate_limit.py:95-100` constructs an in-memory limiter per instance. Local enforcement and retryable admission-backpressure tests pass, not a cluster-wide budget. |
| Complete telemetry with thresholds | **UNVERIFIED.** Profile has thresholds and sampler tests pass, but explicitly distinguishes driver-loop measurements from application-loop measurements and lacks production worker/saturation/reclaim/long-window observations. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** Boot-failure cleanup tests pass. No live active Attempt kill/recovery experiment or physical-work loss/duplication oracle was executed. |
| Long exact-RC/config soak, repeated after changes | **NOT MET by evaluated evidence.** Current evaluator rejects round 30 for `sustain_duration` and `exact_rc_artifact`. `run_soak.py:730-741` always rejects host-preflight equivalence. No exact promotable image/configuration is specified. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED for completeness.** Historical findings preserved; no new live load findings or GitHub mutations. This report records the unresolved release prerequisites, not issue filing. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for promotion.** Historical machine evidence fails the artifact check. This report identifies the tested commit and deterministic commands, not a production image/config soak. |

## Handoff

**BLOCKED for #860 acceptance.** The alleged deterministic failure is stale at
this head; there is no evidenced CI code/ledger repair to make. Repeating the same
CI-repair dispatch cannot establish missing production acceptance prerequisites.
No code, runtime config, tests, historical evidence, ledgers or grants changed.
Only this report is added; no new tests means no inventory delta is needed.

Next action requires an immutable RC image/configuration and an explicit supported
workload scope, a production-topology runner with physical-work and telemetry
oracles, and resolution of the replica-selection requirement. Then execute the
at-least-four-hour exact-artifact soak, including active-work failure/recovery.
Do not substitute a longer host-process preflight or more green unit tests.
No additional issues were started, no remote mutation was made, and the report
is committed locally for handoff only, never integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC production acceptance prerequisites}`.
