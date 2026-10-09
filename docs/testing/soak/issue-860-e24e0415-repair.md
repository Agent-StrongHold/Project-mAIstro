# #860 CI repair — e24e0415

## Disposition

**BLOCKED.** Writer handoff, not integration or promotion approval.
Starting HEAD: `d866f150b49452c4675fa578e7e51731da347d02`, branch `auto-860`.
The starting worktree was clean. Frozen input: the assigned #860 dispatch and
prior result in job `c973d70b94f64ba5b0154c22d64f369b`; no driver `check-*.log`
files were present in the new job directory at initial inspection.

The requested exact-debt-ledger failure does **not** reproduce. The exact
vulture command passes with 1336 findings matching 1336 reviewed identities,
zero unclassified findings and zero forbidden allowlists. No source removal or
ledger amendment is supported by this evidence. No tests changed; no inventory
delta is required. This handoff is the only repository change in this round.

## Fresh validation

Commands ran in the assigned worktree with 1200-second validation timeouts.
Worker logs are retained under
`/home/dev/maistro/jobs/e24e04150ff146d698d3c37d3882ff3c/`.

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | Passed |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1336 identities; reported trusted base `56332162cf63` |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed: 3003 files |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 52 passed |
| `uv run pytest packages/maistro-server/tests -x -q` | 516 passed, 9 skipped, 22 deprecation warnings |
| `DOCKER_HOST=unix:///var/run/docker.sock docker compose -f deploy/docker-compose.prod.yml config --quiet` | Failed: required `TASK_DELEGATION_KEY` missing |
| `git diff --check a8258ee24dd957d0f0b302db4eee90661fe23439...HEAD` | Passed; earlier whitespace finding not reproduced |
| `uv run python scripts/check-doc-links.py` | Passed after adding this handoff; zero broken relative links |
| `uv run python -` importing the current runner and evaluating preserved round-6 JSON | Passed assertions: `sustain_duration` and `exact_rc_artifact` fail; observed duration 90.43 seconds versus 14400 required |

The Compose error is missing runtime configuration, not a demonstrated product
implementation defect. It differs from the preceding attempt's first missing
variable (`ROUTER_API_KEY`); this report records the newly executed result.
No credentials were invented, no services launched and no soak was run.

## Acceptance audit

| #860 criterion | Evidence and verdict |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:152-160` explicitly lacks user/Workspace population, Graph fan-out, successful model/tool work, Canvas and Goal/background reconciliation. The documented preflight mix is not a complete RC profile. |
| At least two application replicas | **UNVERIFIED for current RC.** Compose declares two services, but configuration validation failed before launch. The middleware tests use two ASGI instances, not deployed production replicas. |
| Sustained saturation, queue growth, reclaim, retries and leak observations | **UNVERIFIED.** Executed historical evaluator confirms 90.43 seconds cannot meet the 14400-second minimum. No current sustained workload. |
| Exactly-once admission, Goal reconciliation and physical Attempt fencing | **UNVERIFIED.** Passing probe tests reject empty/conflicting/duplicate receipt identities but do not run physical production work across replicas. `m3a-load-profile.md:197-200` limits the schedule probe to one occurrence whose Run is cancelled before execution. |
| Replica-selection-safe rate limiting/security/degraded behavior | **Counterexample reproduced; broader acceptance UNVERIFIED.** Both parametrizations at `tests/test_soak_promotion_gates.py:439-488` passed: the same identity gets `[200, 200, 429]` on each independent production middleware instance. Actual app wiring is `maistro_server/main.py:628`; `api/rate_limit.py:25-30,72-76` explicitly uses process-local state. Six local burst checks do not establish a shared allowance. |
| Complete telemetry with explicit thresholds | **UNVERIFIED.** Sampler regression tests passed, including actual uv child process observations. No production application-loop, worker, connection/lock, queue, RSS/descriptor and error series was collected for this RC. Driver-loop lag is not application-loop latency. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED.** No deployed active-work restart occurred. Process rejoin and terminal Run counts alone cannot establish absence of physical duplication or loss. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED.** `run_soak.py:635-646,1465` inserts a failing exact-artifact check on the reachable host preflight path. The three four-hour CLI regression cases passed, correctly refusing promotion; longer execution cannot establish artifact equivalence. |
| Findings classified to earliest broken invariant | **UNVERIFIED.** Historical finding records are not proof of classification for an unexecuted current RC soak. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED for current RC.** Historical evidence was preserved and evaluated, not relabeled. This validation report is not an artifact-bound soak pack. |

## Architecture and required unblock

Read repository instructions, documentation authority/quality guidance,
ADR-081, accepted ADR-081426-1f7c and accepted ADR-081626-f383. ADR-081 is still
Proposed. The accepted runtime contract identifies physical work by Attempt;
the canonical Run store owns durable execution fencing. The fencing ADR does
not define lease-expiry takeover. The issue's reclaim request does not authorize
a competing scheduler or implicit timeout takeover. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no authority was changed.

Next owner action: supply the identified promotable image/configuration and
usable deployment dependencies, complete the production-path representative
workload and telemetry, then run the required long soak with physical-work
instrumentation and restart probes. Resolve the replica-selection allowance
contract explicitly. A passing vulture ledger or another host preflight cannot
substitute for those prerequisites. Repeating this unchanged CI repair assignment
cannot establish #860 acceptance.

Progress: checked 1 issue; completed validation and blocked handoff; skipped 0;
1 failed environment validation (Compose). No implementation repair justified by
the passing scanner. No pushes, issue changes, gate weakening or destructive git.
