# #860 — bounded CI repair and acceptance recheck

## Scope and decision

Job `ae7c4f40a3d74bfd8382b7600969ead1`; branch `auto-860`; starting HEAD
`60adfab1fd7e4e8a7fa3c55d164a31afb9189d49`; assigned base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Starting worktree clean.
Frozen item: #860 only. Read the captured issue acceptance and latest primary
comments from `dispatch-context.json`, supplied prior result, repository
instructions and relevant ADRs. No remote re-fetch, GitHub mutation or merge.
Assumption: writer/CI-repair assignment governs the generic verifier instructions.
No current-job `check-*.log` files existed at initial inspection.

**BLOCKED on acceptance, not on the supplied deterministic failure.** The prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports a 24-versus-21 schema
statement mismatch. The current test independently expects all 24 statements,
including the three Gauntlet audit columns, and passes. The exact requested
Vulture scan also passes. There is no evidenced code or ledger repair to make.
Only this report changes; no tests added, so no inventory delta is required.

## Fresh validation

All commands ran in the assigned worktree with long timeouts. Logs are in the
job directory under the names below; these are local checks, not a new soak.

| Command | Outcome | Local log |
| --- | --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323 reviewed identities / 1323 findings; zero unclassified or never-allowlist | `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; database integration cases remain unexecuted | `worker-pg-learnings.log` |
| `uv run ruff check .` | PASS | `worker-ruff.log` |
| `uv run ruff format --check .` | PASS | `worker-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 65 passed | `worker-soak-tests.log` |
| `uv run python -` importing the current driver and evaluating retained round-43 JSON | Duration 420.09 seconds; failed `sustain_duration` and `exact_rc_artifact`; current `preflight_artifact_check()` returns false | `worker-evidence-audit.json` |

The Vulture command matches `.github/workflows/quality.yml:1078` and
`vulture-ratchet.yml:82`. No unbanked identities were reported; the explicit
ledger exception is not a reason to manufacture a ledger diff.

## Architecture and reachable behavior

Read ADR-085 (Accepted), ADR-081626-f383 (Accepted), ADR-082126-f69c
(Accepted), and ADR-081 (Proposed). Preserve `Goal -> Graph -> Run -> NodeRun
-> Attempt`: schedules produce Runs; the canonical Run store owns Attempt
fencing. Admission uniqueness is not proof of physical-effect uniqueness.
The lease ADR explicitly does not itself define expiry takeover. Do not add
an alternate scheduler, Goal store, execution authority or authorization path
to obtain green soak evidence. The proposed deployment ADR does not waive the
exact-RC requirement.

`packages/maistro-server/src/maistro_server/main.py:648` installs production
`RateLimitMiddleware`; `api/rate_limit.py:93` creates its per-instance
`InMemoryRateLimiter`. The executed test at
`tests/test_soak_promotion_gates.py:439` exercises this middleware with the same
credential/IP on two instances. Each accepts two requests before returning 429:
replica selection grants another allowance. This is explicitly documented
process-local behavior, not evidence of a cluster-wide principal budget. A
passing falsification test does not satisfy #860's non-bypass criterion.

## All ten acceptance criteria

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md` documents preflight gaps. `run_soak.py:1373` uses one credential and five traffic classes, not concurrent Workspaces, Graph fan-out, successful provider/tool calls, Canvas or Goal/background work. No selected immutable RC configuration was supplied. |
| At least two application replicas | **UNVERIFIED for the RC.** Executed ASGI middleware tests are not deployed application replicas; current artifact check identifies host-uvicorn preflight. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Re-evaluated historical duration is 420.09 seconds, below the profile's four-hour minimum. No sustained RC run executed. |
| No duplicate physical work; Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044` cancels the admission probe's queued Run without executing it. Admission receipt tests do not account for physical effects or desired-state reconciliation. |
| Security/rate/degraded behavior cannot be bypassed by replica selection | **Contrary local production-middleware evidence reproduced**, as above. Full deployment security/degraded behavior remains **UNVERIFIED**. |
| All required telemetry and explicit thresholds | **UNVERIFIED as a complete RC observation.** Executed sampler test observes real child RSS/descriptors, but `run_soak.py:1410` measures driver loop lag, not application loop lag. No new PostgreSQL contention, queue or complete worker telemetry under RC load. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1427` signals processes and checks rejoin; this round did not run a deployment or account for physical effects across Attempt ownership changes. |
| Long soak of exact RC; invalidate after changes | **UNVERIFIED / BLOCKED.** Executed artifact check at `run_soak.py:730` returns false. Executed CLI tests reject even synthetic four-hour preflight evidence. Historical evidence fails both artifact and duration checks. |
| File/reclassify load findings before promotion | **UNVERIFIED externally.** Captured discussion and historical notes do not prove current disposition of all findings. No issue mutation performed. |
| Publish machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for promotion.** Retained JSON is rejected by the current evaluator. This report records local checks, not a hash-bound RC soak. |

## Handoff

Do not repeat the stale schema repair or amend a clean ledger. Required next
input is the exact immutable RC artifact/configuration and its representative
workload scope, followed by a production-path long soak with complete telemetry
and physical-work/recovery accounting. Resolve or explicitly reconcile the
replica-selection allowance before claiming the non-bypass criterion. Another
short host preflight cannot establish acceptance. No new soak was started.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC deployment evidence and replica-budget resolution"}`.
The supplied validation failure is resolved in the starting tree; issue #860
remains blocked. This report is committed locally for handoff, not integration
approval.
