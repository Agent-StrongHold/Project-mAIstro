# Issue #860 — repair checkpoint (03083eaa)

## Frozen scope

Only issue #860 on `auto-860`, starting at
`3cb52cf1c0a763349d6bd3e897ba6ca8e49e892e`, base
`2154f845347c9541016288c760f8da3f5cd2e064`. Initial worktree clean.
Review surfaces: existing soak runner/profile/promotion tests, relevant ADRs,
prior failure `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`,
and explicitly authorized vulture gate/ledger. No other issues or PRs are work items.
Candidate changes are this report and only evidence-supported repairs on those surfaces.

The dispatch snapshot supplies all ten acceptance criteria. The named prior
result reports BLOCKED; it is not current validation. No `check-*.log` files
were present in this job directory at the initial snapshot.

Assumption: this is a writer CI-repair round, not a verifier-only round.
Do not manufacture exact-RC deployment evidence from local unit tests.

## Results

Exact requested vulture command passed: 1323 reviewed identities / 1323
findings, zero unclassified and zero never-allowlist findings. No ledger repair
is supported by this scan. Historical check-3.log is a different failure:
`test_ensure_schema_fences_ddl_behind_advisory_lock` expected 21 DDL statements
and observed 24. Reproduction and focused acceptance validation follow.

Read accepted ADR-081626-f383 (canonical lease authority), ADR-085
(per-principal rate enforcement), current load profile and adjacent promotion
tests. The profile explicitly calls this a host-process preflight, not an
exact-RC runner, and lists representative-workload gaps. The replica-selection
regression asserts separate allowances on two production middleware instances;
a passing test there is evidence of a limitation, not acceptance success.

Fresh focused pytest: **130 passed, 6 skipped**. Historical schema failure did
not reproduce; the independent expected DDL list now includes the three
Gauntlet audit columns (`test_pg_learnings.py:175–177`). Ruff lint and format
checks passed (3277 files formatted). Deployment claims and execution lifecycle
gates passed; the latter reports 19 classified / 19 discovered lifecycles.
No code, tests, ledger, or inventory changes are justified by these results.
The only changed file is this report. No added tests means no inventory delta.

## Commands executed

Validation commands used 1200-second tool timeouts:

- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed; matches `.github/workflows/quality.yml:1078`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q`: 130 passed, 6 skipped. Live PostgreSQL coverage is not established by skipped tests.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv run python scripts/check-deployment-claims.py`: passed (static existence, not live deployment validation).
- `uv run python scripts/check-execution-lifecycles.py`: passed.

## Architecture and acceptance

Also read accepted ADR-081226-a66b, ADR-082526-b36a and ADR-082826-08f0.
Later renewal/recovery decisions extend the original lease contract: a live
lease forbids redispatch; expired work is reclaimed via the canonical lifecycle
seam. No competing scheduler or authority is introduced. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. Admission counts cannot substitute
for physical-work uniqueness or Goal desired-state reconciliation.

| Criterion | Fresh evidence / residual gap |
| --- | --- |
| Representative RC profile | UNVERIFIED. Existing profile explicitly omits concurrent users/Workspaces, fan-out, successful model/tool work and Design/Canvas/background activity; exclusions need selected-RC justification. |
| At least two deployed replicas | UNVERIFIED. Executed ASGI instances are not deployed application replicas. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, leaks, shutdown | UNVERIFIED. Focused tests take seconds, not a sustained observation window. |
| Schedule/task/Run/Attempt uniqueness and Goal reconciliation | UNVERIFIED under load. Fencing/recovery tests pass at bounded canonical seams; no deployed physical-work counter or sustained Goal workload. |
| Non-bypassable rate/security/degraded behavior | NOT SATISFIED at the middleware seam: `tests/test_soak_promotion_gates.py:439` freshly passes by observing `[200,200,429]` independently on both replicas for the same identity. `rate_limit.py:93` allocates a local limiter; `main.py:648` installs that middleware in production. Full deployed security/degraded behavior UNVERIFIED. |
| Full telemetry and explicit pass/fail thresholds | UNVERIFIED. No fresh production PostgreSQL latency/locks, application-loop, worker/RSS/descriptor/queue/error time series. Driver-loop sampling is not application-loop measurement. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Bounded recovery tests pass, but no deployed active Attempt was killed under sustained traffic. |
| Long exact-RC soak | UNVERIFIED. `scripts/soak/run_soak.py:744` always marks host preflight as not exact-RC; executed CLI regression at `tests/test_soak_promotion_gates.py:103` fails closed even for synthetic four-hour evidence. No immutable RC/configuration designated in this assignment. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness without load. Existing `BACKLOG.md:267` engine-116 tracks the shared-budget gap. No GitHub mutations. |
| Human/machine evidence tied to exact image/package/commit/config | UNVERIFIED. This report is source-head validation, not a hash-bound production soak pack. |

## Handoff

**BLOCKED** for issue acceptance. The supplied CI failure is not reproducible;
the exact-debt ledger already matches the observed scan. Altering expectations,
weakening promotion gates or banking guessed identities would not fix #860.

Next requires an immutable RC/configuration, a representative production-path
profile and a minimum four-hour production soak with full telemetry and active
work recovery evidence. The cross-replica budget gap remains a prerequisite;
repair it through the existing limiter/identity seam, not a new auth path.
Another host-preflight run cannot satisfy this requirement.

Progress: checked 1 issue, acceptance-complete 0, skipped 0, validation errors 0.
This commit is a local handoff only, not integration approval or issue closure.
