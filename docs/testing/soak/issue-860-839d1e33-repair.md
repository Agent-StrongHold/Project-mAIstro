# Issue #860 — bounded CI repair (839d1e33)

## Frozen scope and initial checkpoint

- Sole issue: #860; branch `auto-860`; starting HEAD
  `15ce4681c4d918cc37812837c9a02a49ca1db178`; supplied develop base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Initial worktree is clean. No incoming changes need salvage.
- Process only the supplied dispatch snapshot, prior result, specified failed
  log, vulture gate and its reported identities, and existing #860 acceptance
  seams/tests. Candidate edits: this report, `quality/vulture-baseline.json`
  (explicit CI-repair exception), and genuinely dead identities reported by
  that gate. No unrelated issue repair or GitHub mutations.
- Current job directory initially contains no `check-*.log` files.
- Prior result says BLOCKED; this is historical evidence, not fresh validation.
- Assumption: writer role applies because this is an assigned repair round.
  No exact promotable RC/deployment identity is supplied in the lane brief;
  bounded tests cannot establish long exact-RC production soak acceptance.

## Results

- Exact requested vulture scan PASS: 1322 findings / 1322 reviewed identities,
  zero unclassified and never-allowlist findings. The gate resolves the supplied
  base `321cbdb8fe9b`. No evidence warrants changing the ledger or runtime code.
- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3301 files).
- Historical `98a11313/check-3.log` was read: schema-fence expectation counted
  21 statements against 24 actual. Current test already independently enumerates
  the three audit columns; fresh execution passes.
- Read accepted ADR-081226-a66b, ADR-085 and ADR-082826-08f0. Preserve canonical
  Goal -> Graph -> Run -> NodeRun -> Attempt ownership and liveness-based
  recovery. ADR-085's principal keying does not establish shared replica budgets.
- Current source confirms per-instance in-memory middleware allowances and an
  explicitly non-promotable host-process preflight. These are acceptance gaps,
  not a reason to weaken promotion gates or create new execution authority.

## Executed focused validation

All validation commands used 600- or 1200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 reviewed / 1322 findings; exact workflow arguments (`quality.yml:1079`) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | 57 passed, 6 skipped, 2.16 seconds |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed, 2.53 seconds |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence, not deployment verification |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified / 19 discovered |

Total: 130 passed, 6 skipped. No test added or changed; no inventory delta.
No baseline amendment is justified: there are no unbanked or eliminated identities.

## Reachable behavior

- `packages/maistro-server/src/maistro_server/main.py:648` installs
  `RateLimitMiddleware`; `api/rate_limit.py:93` constructs its own
  `InMemoryRateLimiter`. Executed
  `tests/test_soak_promotion_gates.py:439` exhausts one replica's allowance
  then obtains another on the second for the same authenticated principal or
  unauthenticated address: both return `[200, 200, 429]`. This proves local
  enforcement, not the issue's replica-selection non-bypass requirement.
  It is an ASGI middleware test, not deployed traffic.
- `scripts/soak/run_soak.py:744` always rejects exact-RC artifact equivalence
  for the host-process preflight. Executed promotion tests check fail-closed
  behavior; extending duration cannot turn that runner into production proof.
- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` holds a
  transaction-scoped advisory lock over the schema upgrades. The independent
  ordered expectation at `tests/persistence/test_pg_learnings.py:161` includes
  all 24 statements and passes. The supplied old CI failure is not current.

## Acceptance assessment

| Issue criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC workload | UNVERIFIED. `m3a-load-profile.md` defines a preflight mix but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background-worker coverage. No selected RC applicability supplied. |
| At least two deployed application replicas | UNVERIFIED. Two ASGI middleware instances were tested, not two promoted images. |
| Sustained saturation, queue growth, lease reclaim, retries and leaks | UNVERIFIED. Bounded tests lasted seconds; no long production observations generated. |
| Unique physical work and Goal reconciliation | UNVERIFIED under multi-replica load. Fencing/recovery/admission regressions pass; stale-write rejection and unique admission alone do not prove unique physical execution. |
| Rate/security/degraded enforcement without replica-selection bypass | NOT SATISFIED at the middleware seam: same identity receives a fresh allowance on replica two. Production security/degraded-load acceptance remains UNVERIFIED. |
| Complete PostgreSQL, loop, worker/process, RSS/fd, queue and error telemetry with thresholds | UNVERIFIED. Written thresholds are not complete observed production measurements; driver loop lag is not application loop lag. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED for deployed RC. Canonical recovery regressions pass only at bounded test scope. |
| Long soak of exact RC/configuration, repeated after changes | UNVERIFIED. No immutable RC was supplied; existing preflight rejects equivalence. Profile minimum is four hours. |
| Load findings classified at earliest broken invariant | UNVERIFIED for completeness without representative load. Replica budget gap belongs to prerequisite security/rate enforcement, not throughput optimization; recorded locally, no GitHub mutation. |
| Hash-bound machine/human production evidence | UNVERIFIED. This source-head validation report is not an exact image/package/config soak evidence pack. |

## Final handoff

**BLOCKED**, not promotion-ready. Only this report changes. No runtime, test,
ledger, grant or gate edit was supported by the supplied CI failure or fresh
scan. The inherited production-evidence blocker cannot be resolved by rerunning
bounded tests or by weakening the artifact gate. No develop conflict is present.

Next: provide the immutable RC and normalized deployment configuration, complete
its representative workload coverage, resolve the replica-budget prerequisite
through the canonical security seam, and execute a new exact-artifact soak with
complete telemetry and active-work recovery/physical-work observations. Existing
preflight evidence must not be relabeled as that soak.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. Local commit is a handoff checkpoint, not integration
approval. No GitHub mutations performed.

