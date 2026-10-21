# Issue #860 validation — job 8be8483

## Sync and scope

The assigned starting head was `88b38719cd63f3c9977ab17282ac9ddacb3020e5`; the worktree was clean. The job directory contained no `check-*.log` files. The previous result artifact (`a9031d59`) was reviewed and its blocked status was rechecked against repository evidence. After fetching `origin/develop`, the branch was one commit behind; merged `origin/develop` without conflicts as `83d44dd9c78f04667c57a09c3ca0de56b1d31b6b`. No product code or test files were changed.

## Executed checks on `83d44dd9c78f`

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1321 reviewed identities match 1321 findings; 0 unclassified and 0 never-allowlisted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` — PASS: 92 tests.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — PASS.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — PASS.
- `DOCKER_HOST=unix:///var/run/docker.sock docker compose -f deploy/docker-compose.prod.yml ps` — BLOCKED before startup: Compose requires unset `REDIS_PASSWORD`. No production replicas were started.
- `git diff --check` — PASS.

## Acceptance evidence and disposition

`docs/testing/soak/m3a-load-profile.md` states the current `scripts/soak/run_soak.py` boots host Uvicorn processes, not the production Compose artifact; it requires a minimum 14,400-second run and expressly identifies remaining representative-workload gaps. The checked round-109 evidence (`docs/testing/soak/evidence/m3a-round109-shakedown.json`) records only 420.05 seconds and `exact_rc_artifact.ok=false`; its `git_head` is `5a59c724a20ef1241d57c048df90758f2c2e1e25`, not the candidate. Its passing schedule/task/rate/failover/drain probes are preflight evidence only. The rate evidence itself says enforcement is process-local and aggregate budget scales with replica count. `scripts/soak/run_soak.py::preflight_artifact_check` hard-codes a failing result for the host topology; `failed_promotion_checks` includes exact artifact and duration among mandatory checks.

The accepted ADR-062 keeps Graph execution on the GraphRun/NodeRun protocol. Accepted ADR-081626-f383 places physical Attempt lease/fencing authority in the canonical persistence/Attempt execution seam and explicitly does not establish lease-expiry takeover. These contracts do not permit replacing canonical execution with a soak-only scheduler or interpreting schedule counts as physical-work fencing evidence.

| Criterion | Evidence/status |
|---|---|
| Representative multi-Workspace/users and full release workload | UNVERIFIED: profile gaps remain for concurrent populations, Graph fan-out, successful tool/model calls, Design/Canvas and background/Goal reconciliation. |
| Two production application replicas | UNVERIFIED: production Compose startup blocked on missing `REDIS_PASSWORD`. |
| Sustained soak, saturation/reclaim/leak behavior | NOT MET: 420.05 seconds vs 14,400-second minimum; host preflight only. |
| Exactly-once schedule/task/Run/Attempt work and Goal reconciliation | UNVERIFIED at production grade: probes do not establish physical-work fencing or sustained reconciliation. |
| Rate limiting/security cannot be bypassed by replica selection | UNVERIFIED: probe is process-local and explicitly documents aggregate budget multiplication. |
| Required telemetry and pass/fail thresholds | PARTIAL: preflight metrics exist, but no four-hour production observations. |
| Kill/restart, graceful drain, fencing and recovery in production | UNVERIFIED: only preflight probes; no production replicas started. |
| Exact RC artifact/configuration soak and hashes | NOT MET: no exact candidate RC was run; available evidence identifies a different commit and host topology. |
| Findings reclassified to earliest invariant | UNVERIFIED; no external issue actions taken. |
| Machine/human evidence tied to candidate artifacts | NOT MET for this candidate. |

**Disposition: BLOCKED for issue #860 acceptance.** The runnable local gate checks pass, but they cannot substitute for the required production RC soak; the Compose prerequisite is unavailable in this environment. No tests were added, so no test inventory delta is required. No issue or GitHub actions were taken.

## Revalidation on assigned head `7429311bd409`

The assigned job supplied no `check-*.log` files; no verifier claim was treated as evidence. I read the complete acceptance body from the frozen dispatch snapshot, the profile's remaining gaps, and accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle), ADR-081626-f383 (durable Attempt lease/fencing), and ADR-082526-b36a (lease renewal and reclamation). These preserve the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` execution spine; none allows inferring production soak acceptance from component tests.

Fresh checks on the assigned head:

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — PASS, 85 tests.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1321 reviewed identities match 1321 findings; zero unclassified/never-allowlisted.
- `git status --short` — clean before this report update.

The production behavior remains explicitly fail-closed: `scripts/soak/run_soak.py:744-755` always reports `exact_rc_artifact.ok=false` for its host-Uvicorn preflight. The checked existing profile (`docs/testing/soak/m3a-load-profile.md`, “Remaining representative-profile gaps”) says it lacks concurrent user/Workspace populations, Graph fan-out, successful tool/model calls, Design/Canvas, Goal/background-worker reconciliation, and complete production telemetry/physical Attempt recovery proof. The supplied prior result reports no selected immutable RC/configuration and a 420.05-second host preflight versus the required 14,400 seconds. No production topology run can be claimed from these checks.

All ten issue acceptance criteria remain UNVERIFIED or NOT MET at production acceptance grade: representative workloads; two deployed replicas; sustained saturation/reclaim/leak observations; no duplicate physical work/reconciliation; replica-independent rate/security; required telemetry with thresholds; kill/restart drain/fencing/recovery; exact-RC >=4-hour soak; complete finding classification; candidate-hash-bound machine/human evidence. No tests or product code were changed, so no inventory delta is required. Disposition remains **BLOCKED** pending an owner-designated immutable RC/configuration and a new qualifying production soak; this report commit is not promotion approval.
