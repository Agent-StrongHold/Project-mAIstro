# Issue #860 repair — job 3a45bbe4

## Frozen scope

Assigned branch `auto-860`, starting HEAD
`c9613ad4feec9b501e615ad5f9ad4b54fafa8867`, base
`b1f17b8d6246d347f617fb2c0b969e6798e0152b`. Initial worktree clean.
Only issue #860 is processed; linked issues/PRs are evidence, not work items.

Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`
and its production implementation `packages/maistro-core/src/maistro/persistence/pg_learnings.py`;
`quality/vulture-baseline.json` only for identities confirmed by the assigned scan;
this report and `docs/testing/inventory-notes/m3a-860-3a45bbe4-schema-fence.md`.
Read-only validation includes the existing soak scripts/tests/evidence and relevant ADRs.

The current job directory contains no `check-*.log` files. Supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports the schema-fence test
expected 21 DDL statements but observed 24. Prior result `760f75c4` reports
BLOCKED, not a develop merge conflict. Assumption: repair that concrete failure
and scan-confirmed debt, without claiming local preflight equals exact-RC soak.

## Progress

- Exact vulture scan PASS: 1332 findings / 1332 reviewed identities, zero
  unclassified or forbidden. No ledger amendment is warranted.
- Fresh schema test module: 37 passed, 6 skipped. The supplied failure is stale:
  the current expected DDL already includes all three Gauntlet validation columns.
  No production/test change is warranted; no inventory delta is needed.
- Remaining work is focused acceptance validation and a committed handoff. Do not
  manufacture another repair or widen into sibling implementation issues.

## Executed validation

All commands ran in the assigned worktree, with 1200-second validation timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1332 reviewed / 1332 findings, zero unclassified/forbidden; matches the quality workflow invocation. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped. No live PostgreSQL fencing proof is claimed for skipped tests. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3105 files already formatted. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 82 passed, including production-middleware replica-selection tests and sustained-admission regression cases. |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 28182 unique identities, no duplicate evidence. |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items. |
| `uv run python -` importing the current soak runner and evaluating preserved `m3a-round6-shakedown.json` | PASS: asserted `sustain_duration` and `exact_rc_artifact` fail; recorded duration 90.43 seconds; current `preflight_artifact_check()['ok']` is false. This is re-evaluation, not a new soak. |
| `git diff --check` | PASS. |

## Architecture reconciliation

Read repository instructions and documentation authority hierarchy, accepted
ADR-081226-69ee (canonical Graph/Run/NodeRun/Attempt), accepted ADR-081626-f383
(Run-store-owned execution fencing), and accepted ADR-085 (principal-keyed rate
limiting). ADR-081 is Proposed, not an accepted exception to evidence requirements.
Lease-expiry takeover is explicitly outside the accepted fencing contract; issue
wording does not authorize inventing reclaim authority. Goal -> Graph -> Run ->
NodeRun -> Attempt is preserved. No production behavior or authority changed.

## Acceptance review

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Reviewed `m3a-load-profile.md:153-172`: one API key, no user/Workspace population, fan-out, successful model/tool, Design/Canvas or background reconciliation coverage. RC applicability remains unresolved. |
| At least two production application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26-78` defines two services, but executed tests use ASGI instances, not running RC containers. |
| Sustained saturation, queue growth, lease expiry/reclaim, retries, memory/descriptor/process leaks and shutdown | UNVERIFIED. Executed sampler tests are not sustained application load; re-evaluated 90.43-second evidence fails the duration gate. No new live soak ran. |
| No duplicate physical work for schedule/task/Run/Attempt/Goal operations | UNVERIFIED. Admission/backpressure tests pass but are not a physical-work or Goal-reconciliation oracle. The profile's schedule probe cancels its queued Run without execution. |
| Rate/security/degraded enforcement cannot be bypassed by replica selection | NOT MET for an aggregate principal budget: executed `tests/test_soak_promotion_gates.py:439-488` confirms the same identity gets `[200,200,429]` independently from each middleware instance. Production registers this middleware at `maistro_server/main.py:648`; `api/rate_limit.py:72` constructs an in-memory limiter per instance. Process-local enforcement is intentional/documented, not proof of the stronger issue criterion. Sustained security/degraded behavior remains UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED. Existing accounting/sampler tests pass; profile admits driver loop lag is not application event-loop lag. Complete production pool/worker/error/leak observations are absent. |
| Active-work replica kill/restart with drain/fencing/recovery | UNVERIFIED. Boot cleanup tests pass but do not correlate physical Attempts through live recovery. |
| Long-running exact RC artifact/configuration soak | NOT MET by re-evaluated evidence: 90.43 seconds, rejected exact-artifact gate. `scripts/soak/run_soak.py:730-741` explicitly cannot attest production Compose equivalence. No immutable selected RC was established in this round. |
| Findings filed/reclassified to earliest broken milestone invariant | UNVERIFIED. Backlog consistency passes; external filing completeness is not established. No GitHub mutations permitted or performed. |
| Machine/human soak evidence tied to exact image/package/commit/config hashes | UNVERIFIED. Existing preflight evidence is preserved; this document is validation evidence only, not a production soak certificate. |

## Disposition and handoff

**BLOCKED for issue #860 acceptance.** Historical CI failure is no longer
reproducible; the requested ledger gate is clean. No code, test, gate, ledger or
grant changes are justified. Only this report changed; no test inventory delta
is needed. This avoids repeating already completed repairs or treating passing
unit/static checks as promotion evidence.

Next: the release owner must select the immutable RC/config and representative
workload applicability, reconcile the process-local rate-budget claim with the
non-bypass acceptance requirement, and supply physical-work/recovery oracles.
Then execute and publish a fresh >=4-hour exact-artifact production soak with
all required telemetry and image/config hashes. Do not repeat the stale
schema/vulture repair without a new failing command.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC production acceptance prerequisites}. Local validation/handoff
complete; issue acceptance remains blocked. No integration approval, remote
mutation, destructive cleanup, or discarded work.
