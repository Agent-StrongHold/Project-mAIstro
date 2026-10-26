# Issue #860 — aac5e93a blocked repair handoff

## Frozen scope

- Only issue #860; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `5917d57652fa84f56207ccddbfe1b0b7761569df`.
- Supplied develop base: `a8258ee24dd957d0f0b302db4eee90661fe23439`.
- Input: captured `dispatch-context.json` in job `aac5e93a3d4b45edb13961b85aa7da30`; no live GitHub enumeration or mutations.
- Repair files: this report and `quality/vulture-baseline.json`, only if the exact CI scan demonstrates reviewed retained identities. Production source repair is not assumed necessary.
- Read-only validation scope: repository instructions, relevant accepted ADRs, existing soak harness/profile/evidence/tests, exact vulture gate and its implementation/workflow.
- Initial worktree was clean and HEAD matched assignment. No `check-*.log` files were present in the job directory at initial inspection.

## Interpretation

This is a writer CI-repair round with explicit permission to amend the vulture identity ledger. It is not permission to weaken gates or to present historical shakedowns as an exact-release-candidate production soak. Missing deployment evidence will remain a blocker. No competing execution, authorization, or event authority will be introduced.

## Progress

- Dependency restoration (`uv sync --locked --extra dev`) passed.
- Exact CI vulture scan passed: 1336 findings match 1336 reviewed identities; zero unclassified or forbidden-allowlist findings. It reports trusted base `56332162cf63`. No ledger amendment or source deletion is justified; ledger remains untouched.
- Read captured issue body/latest comments and prior result. Prior claims are not treated as fresh validation.
- An overbroad read-only `find ..` during initial inspection timed out at 120 seconds; replaced with bounded tracked-file inspection. No files were changed by it.
- Read accepted ADR-081426-1f7c and ADR-081626-f383: Attempt identity owns physical execution; the canonical Run store owns durable fencing. Lease-expiry takeover is explicitly not defined, so the issue cannot authorize implicit timeout takeover. ADR-081 remains Proposed. No architectural changes are planned.
- Current profile explicitly lacks representative users/Workspaces, successful Graph/tool/Canvas work and sustained Goal/Attempt recovery. Fresh acceptance validation below confirms these remain unproven.

Logs for fresh commands are retained under the assigned job directory as `worker-*.log`.

## Fresh validation results

Validation used 1200-second timeouts, except initial inspection (120 seconds).

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | Passed |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed; 1336 matching reviewed identities |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 3003 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 52 passed |
| `uv run pytest packages/maistro-server/tests -x -q` | 516 passed, 9 skipped, 22 deprecation warnings |
| `DOCKER_HOST=unix:///var/run/docker.sock docker compose -f deploy/docker-compose.prod.yml config --quiet` | Failed (exit 1): required `POSTGRES_PASSWORD` missing |
| `git diff --check a8258ee24dd957d0f0b302db4eee90661fe23439...HEAD` | Passed; prior whitespace findings do not reproduce |
| `uv run python -` importing the current runner and evaluating the preserved round-6 JSON | Passed assertions: fails `sustain_duration` and `exact_rc_artifact`; 90.43 seconds versus 14400 required; historical commit differs from assigned HEAD |
| `uv run python scripts/check-doc-links.py` | Passed; zero broken relative links |

The Compose failure is a missing environment prerequisite, not evidence of a new implementation defect. No deployment was launched, credentials fabricated or current soak claimed. The previous attempt reported a different first missing variable; this report records the command actually executed in this round.

## Acceptance audit

| #860 criterion | Executed evidence or explicit limitation |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `m3a-load-profile.md:152-165` records missing user/Workspace population, Graph fan-out, successful tool/model work, Canvas and Goal/background reconciliation. The preflight profile does not establish applicability to a selected RC configuration. |
| At least two application replicas | **UNVERIFIED for current RC.** Production Compose declares two services, but configuration validation failed before deployment. Passing ASGI tests are not deployed replicas. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leak observations | **UNVERIFIED.** Fresh historical-evidence evaluation rejects 90.43 seconds against the 14400-second minimum. No current sustained load or leak series was collected. |
| Exactly-once schedule/task/Run/Attempt work and Goal reconciliation | **UNVERIFIED.** Existing probe tests pass and reject missing/duplicate receipt identities, but do not execute physical production work across replicas. The profile at lines 197-200 acknowledges that the schedule probe cancels its one Run before execution. Accepted fencing ADR does not authorize implicit expiry takeover. |
| Replica-selection-safe rate limiting, security and degradation | **Counterexample reproduced; broader acceptance UNVERIFIED.** Both parametrizations of `tests/test_soak_promotion_gates.py:439-488` pass: the same credential/IP receives `[200, 200, 429]` on each independent production middleware instance. Reachable app wiring is `maistro_server/main.py:628`; `api/rate_limit.py:25-30,72-76` explicitly instantiates process-local state. This is consistent with its documented local allowance but cannot prove #860's stronger replica-selection claim. No alternate authorization path was introduced. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** Sampler tests include actual uv child memory/descriptor observations, but no current production application-loop, worker, DB contention, queue, RSS/descriptor or error series exists from this round. Profile lines 157-165 distinguish driver-loop lag from application-loop latency and list measurement gaps. |
| Kill/restart during active work and physical drain/fencing/recovery | **UNVERIFIED.** No current production active-work restart occurred. Historical rejoin/terminal Run observations cannot establish absence of physical duplication/loss. |
| Long soak of exact RC image/configuration | **UNVERIFIED.** `run_soak.py:635-646,1465` explicitly rejects certification on its host preflight path. All three four-hour CLI regression cases pass by refusing promotion without exact-artifact evidence. No identified deployable RC or complete runtime configuration was supplied. |
| Findings classified to earliest broken milestone invariant | **UNVERIFIED for current load.** No current load run exists to classify. Historical reports remain unchanged; GitHub mutations are prohibited and were not performed. |
| Machine/human evidence tied to exact artifact/config hashes | **UNVERIFIED for current RC.** Preserved round-6 evidence identifies `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned HEAD. Fresh validation logs and this report are not an artifact-bound production soak pack. |

## Disposition and next action

**BLOCKED**, not merge/promotion approval. Exact-debt-ledger failure does not reproduce; editing an already matching ledger would be cosmetic or introduce a defect. Only this report changed; no production code, gates, ledgers or tests changed. Consequently no test-inventory delta is required.

Unblock by supplying the selected promotable image/configuration and usable deployment dependencies, completing representative production workloads and application telemetry, resolving the replica-selection allowance contract, and running the required long soak with physical Attempt instrumentation and restart probes. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and canonical authority. Another identical CI-repair dispatch cannot supply that missing evidence.

Progress: checked 1 assigned issue; completed validation and blocked handoff; skipped 0; errors 1 deployment-prerequisite failure (plus the recorded initial read-only inspection timeout). Next: deployment/RC owner prerequisites and production-path soak work. No pushes or GitHub mutations.
