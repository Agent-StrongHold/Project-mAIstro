# Issue #860 — repair checkpoint (32b18d1c)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `5756cef25508d1482a861ae6806d1628d27f6061`.
- Supplied develop base: `658a8f78c1800d264759a81dc8d87dd447f0f7f2`.
- Starting worktree clean; no incoming edits to salvage.
- Process the supplied dispatch snapshot only; no GitHub mutations.
- Repair scope: observed vulture per-identity failures, adjacent tests/inventory
  notes if behavior changes, and this validation report. No new runtime authority.
- Inspect existing soak scripts, tests, production integration, relevant ADRs and
  evidence to assess all ten acceptance criteria; do not expand into unrelated fixes.

## Initial observations

The supplied job directory contains no `check-*.log` files. Deterministic validation
must be run locally. The issue requires a long-running exact-RC production soak;
prior evidence is not assumed valid for the assigned HEAD.

Ambiguity: this is a writer repair assignment, not a read-only verifier assignment.
Proceed with focused evidence-based repair and a local commit. Promotion remains
blocked unless every acceptance criterion is independently demonstrated.

## Vulture repair disposition

Executed the assigned exact scan:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
It exited 0: 1,338 reviewed identities match 1,338 findings, zero unclassified
and zero never-allowlist findings. The gate resolved its comparison base to
`cd5618223cbd`, not the supplied develop base. There are no observed unbanked
identities to repair or amend; inventing ledger changes would violate the
evidence-based repair requirement. This subtask is complete without code edits.

Relevant architecture inspected: accepted ADR-085 requires per-principal rate
limiting; accepted ADR-081626-f383 requires canonical Attempt lease fencing.
ADR-081 is Proposed, not an accepted waiver of the issue's deployment criteria.
The existing middleware explicitly enforces process-local budgets. Preserve the
canonical authority and report this mismatch rather than adding a new limiter,
scheduler or execution path in a soak-evidence repair.

## Focused validation checkpoint

- `uv run ruff check .`: exit 0, all checks passed.
- `uv run ruff format --check .`: exit 0, 2,943 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  exit 0, 61 passed in 2.78s. This includes real production middleware
  counterexamples for authenticated and unauthenticated replica selection,
  process-group sampling, fail-closed artifact gates, Compose configuration
  contracts and task backpressure. It is not a live production soak.
- `git diff --check 658a8f78c1800d264759a81dc8d87dd447f0f7f2...HEAD`:
  exit 0; the supplied historical whitespace failure does not reproduce.

The retained `evidence/m3a-round6-shakedown.json` records 90.43 seconds,
`git_head=b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, and a failed 14,400-second
duration threshold. Its rate probe predates the complete six-path probe.
Current production `RateLimitMiddleware` constructs an `InMemoryRateLimiter`
per middleware instance. Tests observe `[200, 200, 429]` independently on both
instances for the same identity; replica selection gains fresh allowance.

Additional executed validation:

- `uv run python scripts/check-backlog-consistency.py`: exit 0; 168 items
  parse with valid markers/citations/closure evidence. This does not establish
  that every load finding has been reclassified correctly.
- `uv run python -` importing the current soak evaluator and evaluating the
  retained round-6 JSON: exit 0; asserted rejection on `sustain_duration` and
  `exact_rc_artifact`, and asserted its HEAD differs from the assigned HEAD.
- Production reachability inspection: `maistro_server/main.py:593` installs
  `RateLimitMiddleware`; its constructor at `api/rate_limit.py:72` allocates
  process-local enforcement. The counterexample is not an unused helper.

No test or production code changed, so there is no inventory delta. No ledger,
grant, deployment configuration or historical evidence was amended. Existing
files and prior commits are preserved.

## Acceptance assessment (all ten criteria)

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative users/Workspaces, request mix, Graph/tools/Canvas/workers | UNVERIFIED: inspected profile explicitly excludes these workloads at `m3a-load-profile.md:152-160`; current tests do not fill the gaps. |
| At least two production application replicas | UNVERIFIED: Compose contract tests pass but do not boot two production artifacts. Historical host replicas are not equivalent. |
| Sustained saturation, queue growth, reclaim, retry and leak observations | UNVERIFIED: retained JSON records 90.43 seconds, below 14,400 seconds; no new sustained run executed. |
| Schedule/task/Run/Attempt/Goal physical-work fencing | UNVERIFIED: observed admission identities are not physical-work deduplication; the profile admits the schedule probe cancels its Run. Accepted ADR-081626-f383 and ADR-082526-b36a require canonical fencing and renewal/reclaim, not a parallel scheduler. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET: both production-middleware counterexample cases pass, demonstrating fresh allowance on replica 2. Local 429/backpressure tests pass but cannot prove a shared budget. |
| Complete telemetry with thresholds | UNVERIFIED: process-group sampler tests pass; historical wrapper RSS and driver-loop latency do not measure application-loop latency or complete worker/resource behavior. |
| Kill/restart during active work with physical drain/fencing/recovery | UNVERIFIED: historical exit/rejoin is not proof against silent physical loss/duplication; no current production run executed. |
| Long-running exact-RC soak | NOT MET: current evaluator rejects retained evidence; `run_soak.py:635-646` deliberately reports the host preflight as not an exact RC artifact. |
| Findings classified to earliest broken milestone invariant | UNVERIFIED for completeness: backlog consistency passes; no new under-load finding obtained and no GitHub action taken. |
| Machine/human evidence bound to exact promoted hashes | UNVERIFIED for current RC: historical evidence exists, but its commit differs and it lacks production application-image/config identity. |

## Handoff

Verdict: **BLOCKED**, not merge-ready. The assigned scanner failure does not
reproduce; the substantive acceptance blockers do. There is no develop-sync
conflict in this clean starting worktree, so no merge/fetch was attempted.

Do not repeat a host preflight or amend a passing ledger to claim completion.
Next work needs an exact-RC production runner and representative workload,
application-side telemetry and physical-work recovery assertions, plus resolution
of the replica-budget contract gap. Then execute at least the profile's four-hour
soak on the frozen production image/config and publish its observed identities.
A longer invocation of the current host runner cannot satisfy that requirement.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0;
errors 0 validation command failures. Scanner repair subtask complete (no findings
to amend). Only this report changes in this round; commit locally, never push.
