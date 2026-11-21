# Issue #860 repair — job 8338aee6

## Frozen scope

- One issue: #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `fe97e32c804c1c49ccfc3e7d792c0cf5c2c70fe3`; supplied develop reference: `b78637f52be33c53d49aca1aa5738e3ab820aad3`.
- Clean initial worktree; no uncommitted salvage needed.
- Process only the supplied dispatch snapshot, not remote issue/PR updates.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production counterpart `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, `quality/vulture-baseline.json` (explicit CI-repair exception), and an associated inventory note if tests change. This report records validation and unresolved acceptance.
- Acceptance inspection: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, production rate-limit/task admission paths and adjacent tests, `docs/testing/soak/m3a-load-profile.md`, existing soak evidence, relevant ADRs and gate scripts/workflow.

## Initial evidence and assumptions

The supplied previous `check-3.log` fails the ordered schema-fence assertion
(24 actual statements versus 21 expected). Reproduce before repairing.
The previous result says promotion remains blocked; that claim is not taken as
current verification. No `check-*.log` files were supplied in this job directory.
The supplied develop reference is newer/divergent from this lane; a two-dot diff
is not a lane-only change list. No merge conflict exists, so no speculative sync
or unrelated reconciliation is attempted.

## Results

Fresh reproduction: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed (37 passed, 6 skipped). The expected ordered DDL now includes the three Gauntlet audit columns at lines 175–177; the supplied historical failure does not reproduce.

Exact CI scan: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passed (1332 reviewed identities / 1332 findings; zero unclassified/forbidden). No unbanked or eliminated identity warrants a ledger amendment. No test/production/gate edit is justified by these results.

## Executed validation

Commands ran in the assigned worktree with 1200-second timeouts.

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1332/1332 identities; invocation matches `.github/workflows/quality.yml:1013-1016` |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 104 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3105 files |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 28182 unique identities, zero duplicate evidence |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items |
| `uv run python -` loading the current soak module and preserved `m3a-round6-shakedown.json` | Asserted failed gates include `sustain_duration` and `exact_rc_artifact`; observed 90.43s versus 14400s required; current `preflight_artifact_check()['ok']` is false |
| `git diff --check` | PASS |

The schema test is meaningful: it asserts the transaction boundary, advisory-lock
key and position, and independently listed complete ordered DDL, rather than
copying production constants. Production `pg_learnings.py:215-216` acquires the
transaction and lock before executing DDL. Six skipped PostgreSQL tests are not
live database evidence.

## Architecture reconciliation

Read repository instructions, the documentation authority map, accepted
ADR-081226-69ee, ADR-081626-f383, ADR-085, and the later lease/recovery decisions
ADR-082526-b36a and ADR-082826-08f0. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model. Unlike the original fencing
ADR's historical boundary, the later accepted decisions **do** define lapsed-lease
reclamation, heartbeat renewal and canonical lifecycle reconciliation. A soak
must exercise those existing seams, not invent recovery authority or assume that
restart alone permits taking over live leased work.

ADR-085 requires principal-keyed limits. The production middleware uses the
canonical principal resolver but constructs `InMemoryRateLimiter` per instance
(`api/rate_limit.py:72`), and is wired in `main.py:648`. Executed tests observe
`[200, 200, 429]` on each of two instances for the same identity, both authenticated
and unauthenticated (`tests/test_soak_promotion_gates.py:439-488`). This proves
local enforcement and falsifies a shared principal allowance, not all possible
security claims. No authorization path or rate policy was changed.

## Acceptance against current reachable behavior

| # | Issue criterion | Evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC load profile | UNVERIFIED. `m3a-load-profile.md:153-172` names missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background reconciliation. No immutable RC configuration is designated in this dispatch. |
| 2 | At least two production application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26-76` declares two services; executed ASGI tests are not a live Compose deployment. |
| 3 | Sustained saturation, queue growth, reclaim, retry and leak observations | UNVERIFIED. Executed evaluator rejects the sampled historical 90.43s evidence against the four-hour minimum. No new sustained production load ran. |
| 4 | Exactly-once/fenced physical work across replicas, including Goals | UNVERIFIED. `m3a-load-profile.md:195-204` acknowledges the occurrence probe cancels its queued Run without executing it. Admission tests cannot prove physical-work deduplication. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance: executed production-middleware test cited above demonstrates fresh allowance on replica 2. Other sustained security/degraded behavior is UNVERIFIED. |
| 6 | Complete telemetry with explicit thresholds | UNVERIFIED. Profile documents driver rather than application loop lag and incomplete worker/pool/reclaim/leak observations. Unit-test success is not production telemetry. |
| 7 | Active-work kill/restart, drain, fencing and recovery | UNVERIFIED. No live active-Attempt restart experiment ran; boot contracts do not establish it. |
| 8 | Long-running exact RC artifact/configuration soak | NOT MET by evaluated evidence. Both duration and artifact gates fail. `scripts/soak/run_soak.py:730-741` explicitly rejects the host preflight as production artifact proof even if run longer. |
| 9 | Load findings filed/reclassified before promotion | UNVERIFIED. Backlog consistency passes; it does not establish filing completeness. No GitHub mutation attempted. |
| 10 | Machine/human soak evidence bound to image/package/commit/config hashes | UNVERIFIED for production. Existing artifacts remain intact; this report is a validation handoff, not a production soak attestation. |

## Handoff

**BLOCKED** on #860 acceptance. The supplied historical CI failure is already
fixed, and the exact ledger gate is clean. Only this report changed; no tests
added, so no inventory-delta note is required. No speculative ledger edits,
policy weakening, remote mutations, or unrelated develop sync were performed.

Next requires release-owner selection of the immutable RC/configuration and
workload applicability, resolution of aggregate rate-budget semantics, then a
production-topology runner with physical-work/recovery oracles and complete
telemetry for the four-hour profile. Another short emulator run or redispatch
of the stale schema failure cannot prove these criteria. This documentation-only
commit does not certify earlier artifacts or approve integration.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: production RC
acceptance prerequisites}. The validation handoff is complete; issue acceptance
is not.
