# #860 CI-repair handoff — c973d70b

## Disposition

**BLOCKED; not promotion or integration approval.** This writer rechecked the
assigned `auto-860` starting commit
`bfa9024d1e3cc5166f4cceacf7dc8262f365081a` against the frozen dispatch for #860.
The worktree was clean. No driver `check-*.log` files were supplied in this job;
the checks below were executed locally, not inherited from earlier verdicts.

The explicit vulture repair request has no remaining reproducible failure:
the exact CI command reports **1336 findings matching 1336 reviewed identities**,
zero unclassified and zero forbidden allowlists. No source or ledger amendment
is justified. No tests were added or removed, so no inventory delta is needed.
This handoff is the only repository change in this round.

## Fresh validation

Logs are in the external job directory
`/home/dev/maistro/jobs/c973d70b94f64ba5b0154c22d64f369b/`.

| Command | Executed outcome | Log |
| --- | --- | --- |
| `uv sync --locked --extra dev` | Passed | Console |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed; 1336 identities, default trusted base `56332162cf63` | `check-vulture-worker.log` |
| `uv run ruff check .` | Passed | `check-ruff-worker.log` |
| `uv run ruff format --check .` | Passed; 3003 files formatted | `check-format-worker.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 52 passed | `check-soak-tests-worker.log` |
| `uv run pytest packages/maistro-server/tests -x -q` | 516 passed, 9 skipped, 22 deprecation warnings | `check-server-tests-worker.log` |
| `DOCKER_HOST=unix:///var/run/docker.sock docker compose -f deploy/docker-compose.prod.yml config --quiet` | Failed before deployment: required `ROUTER_API_KEY` missing | `check-compose-worker.log` |
| `git diff --check a8258ee24dd957d0f0b302db4eee90661fe23439...HEAD` | Passed at starting HEAD; earlier whitespace finding not reproduced | `check-diff-worker.log` |
| `uv run python scripts/check-doc-links.py` | Passed; 1865 Markdown files, zero broken links | `check-doc-links-worker.log` |
| `uv run python -` importing the actual runner and evaluating the preserved round-6 JSON | Passed assertions: historical evidence fails both `sustain_duration` and `exact_rc_artifact` | `check-historical-evidence-worker.log` |

The Compose failure is an unavailable runtime configuration, not proof of a
Compose implementation defect. The reference artifact also requires a reachable
model gateway and credentials (`deploy/docker-compose.prod.yml:46-58`). Inventing
placeholder values would not identify the configuration #89 intends to promote.
No containers were started and no long-running soak was executed in this round.

## Acceptance audit (all ten issue criteria)

| Criterion | Current reachable evidence and remaining obligation |
| --- | --- |
| Representative release-candidate profile | **UNVERIFIED.** The profile exists, but `m3a-load-profile.md:152-160` explicitly omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls and Design/Canvas traffic. No complete RC workload demonstrated. |
| Two application replicas | **UNVERIFIED for current RC.** Compose declares two services; configuration validation failed before launch. ASGI test instances are not deployed replicas. |
| Sustained saturation, reclaim, retries and leak observations | **UNVERIFIED.** Historical round-6 evidence records only 90.43 seconds against a 14400-second minimum, not a current sustained run. |
| Exactly-once admission, Goal reconciliation and physical fencing | **UNVERIFIED.** Probe regression tests reject missing/duplicate receipt identities, but do not execute production physical work across replicas; `m3a-load-profile.md:197-200` explicitly limits the single-occurrence schedule probe. |
| Replica-selection-safe rate limiting/security/degraded behavior | **Counterexample reproduced; broader criterion UNVERIFIED.** The two parametrizations of `test_replica_selection_has_an_independent_production_allowance` passed: the same identity receives `[200, 200, 429]` independently on each production middleware instance. This is documented process-local behavior (`rate_limit.py:25-30,72-76`), wired into the actual app at `maistro_server/main.py:628`, not proof of a cluster-wide allowance. |
| Full production telemetry and thresholds | **UNVERIFIED.** Process-group sampler tests passed, but no current production sample series or application-loop/worker telemetry was captured. Driver-loop lag is not application-loop latency. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** No deployed active-work restart occurred; process exit and terminal Run counts cannot prove physical-work fencing. |
| Long soak of exact promoted artifact/configuration | **UNVERIFIED.** `run_soak.py:635-646` always rejects host preflight artifact identity. Three `test_four_hour_preflight_cannot_pass_cli` cases passed; merely extending this driver to four hours cannot satisfy the criterion. |
| Findings filed/reclassified to earliest broken milestone | **UNVERIFIED.** Existing finding documentation does not establish that every current load finding is classified. No GitHub mutations were permitted or performed. |
| Machine/human evidence tied to exact artifact hashes | **UNVERIFIED for current RC.** Historical evidence is preserved, not relabeled as this commit/configuration. This validation handoff is not soak evidence. |

## Architecture reconciliation and next owner action

Read repository instructions, the documentation authority map, quality-gate
policy, ADR-081, accepted ADR-081426-1f7c and accepted ADR-081626-f383.
ADR-081 remains **Proposed**, not authority to assert a production capability.
The accepted contracts keep execution identity at Attempt, with durable lease
fencing owned by the canonical Run store. The fencing ADR explicitly does not
establish lease-expiry takeover; the issue's reclaim request cannot authorize a
new scheduler or recovery authority. Preserve `Goal -> Graph -> Run -> NodeRun
-> Attempt`; none was changed here.

Provide an identified RC image/configuration and usable deployment dependencies,
then execute a production-path representative soak (at least four hours), with
physical-work instrumentation and restart probes. Resolve the replica-selection
allowance contract rather than treating six independent burst checks as proof of
a shared budget. Do not resubmit this unchanged preflight as promotion evidence
or change the passing ledger solely because the dispatch requests a CI repair.

Progress: checked 1 assigned issue; completed validation and blocked handoff;
implementation repair not justified by the vulture scan; #860 acceptance remains
blocked. No pushes, issue changes, gate weakening or destructive git operations.
