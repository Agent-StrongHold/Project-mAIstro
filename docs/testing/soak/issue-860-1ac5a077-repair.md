# Issue #860 — current CI evidence and blocked handoff

## Frozen scope and disposition

One issue checked: #860, branch `auto-860`, exact starting HEAD
`286ad119c629d2ab24a1daf519b9522d2c198441`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Initial worktree was clean.
No remote operations, other issue work, or destructive Git operations performed.
This report is the only repository change. No new tests, inventory delta, ledger
amendments, or production changes are justified by the current repair checks.

The job directory initially contained no driver `check-*.log` files. Read the
explicitly supplied historical `98a11313167b41a98a420abfda80c292/check-3.log`
and prior result, then independently executed the checks below. The historical
24-versus-21 schema assertion failure does **not** reproduce: the independent
expected DDL list already includes the three validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:173–177`.
Production runs these upgrades under the transaction advisory lock at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–222`.

## Fresh commands and outcomes

Validation timeout: 1200 seconds. Logs are in
`/home/dev/maistro/jobs/1ac5a077866847ec82a3429c9c5b4967/`.

| Command | Outcome | Log |
| --- | --- | --- |
| `uv sync --locked --extra dev` | PASS | terminal output |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 findings, 1322 reviewed identities, zero unclassified/never-allowlist | `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped | `worker-schema.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed | `worker-soak-tests.log` |
| `uv run ruff check .` | PASS | `worker-ruff.log` |
| `uv run ruff format --check .` | PASS: 3301 files already formatted | `worker-format.log` |

The vulture CI-repair exception permits reviewing actual scanner drift; it does
not justify changing a ledger that already exactly matches. PostgreSQL skips
are not counted as integration proof. No full-tree pytest run was attempted.

## Reachable behavior and architecture

Read repository instructions, the documentation authority hierarchy, accepted
ADR-081226-a66b (canonical lifecycle), ADR-081626-f383 (lease fencing), ADR-085
(principal rate limits), and ADR-073126-c4e1 (RC/release provenance).
No competing execution, persistence, scheduling, event or authorization path
was introduced. Goal -> Graph -> Run -> NodeRun -> Attempt remains authoritative.

The production app installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`. Its constructor creates
an instance-local `InMemoryRateLimiter` at `api/rate_limit.py:93`.
The executed test at `tests/test_soak_promotion_gates.py:439` uses this actual
middleware and the same client identity across two ASGI apps. Each independently
returns `[200, 200, 429]`, both authenticated and unauthenticated. It is a bounded
counterexample to a shared allowance, not a deployed RC soak. ADR-085's principal
keying does not by itself establish replica-independent enforcement. The existing
process-local contract cannot be relabeled as satisfaction of #860's stronger
replica-selection criterion.

`scripts/soak/run_soak.py:744` explicitly reports `ok: False` for its host-process
artifact check. Extending that emulator's duration cannot establish equivalence
to the promoted image and normalized production configuration. Keep this fail-
closed guard intact. A source branch HEAD is not an immutable RC image identity.

## Acceptance audit

| Issue criterion | Current evidence and disposition |
| --- | --- |
| Representative release-candidate load profile | UNVERIFIED. `m3a-load-profile.md` explicitly records missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background workloads. Applicability must be resolved against the selected RC. |
| At least two supported deployed application replicas | UNVERIFIED. Two ASGI middleware instances are not two deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, resource leaks | UNVERIFIED. The checks above are bounded tests, not sustained load. |
| No duplicate physical work for schedule/task/Run/Attempt/Goal paths | UNVERIFIED. Admission/gate tests cannot certify all physical execution paths under load. |
| Effective rate/security/degraded behavior independent of replica selection | NOT SATISFIED at the production middleware seam: the executed same-identity test observes independent allowances. Broader deployed security/degraded behavior UNVERIFIED. |
| PostgreSQL, application-loop, worker, RSS, descriptor, queue, error telemetry and thresholds | UNVERIFIED. No new production telemetry collected; driver-loop lag is not application-loop latency. |
| Active-work kill/restart with drain, fencing and recovery | UNVERIFIED. No deployed RC restart executed. |
| Long soak of exact RC/configuration, repeated after changes | UNVERIFIED. Runner explicitly rejects artifact equivalence; no immutable promotion artifact/configuration selected in this assignment. |
| Load findings classified to earliest broken invariant | UNVERIFIED for completeness. The observed allowance gap is prerequisite rate/security enforcement, not throughput optimization. No GitHub filing permitted or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for production soak. This report and local test logs identify the tested source head only. |

## Required next transition

**BLOCKED**, not a remaining vulture/schema CI failure or develop-sync conflict.
Provide the selected immutable RC artifact and normalized supported runtime
configuration, resolve the replica-independent enforcement prerequisite through
the existing security seam, and execute the representative multi-replica soak
with physical-work observations and complete telemetry. Do not schedule another
identical bounded CI repair as a substitute for those inputs and execution.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. The local commit is a blocked handoff, not integration or
promotion approval.
