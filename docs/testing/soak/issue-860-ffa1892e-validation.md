# Issue #860 repair checkpoint — ffa1892e

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `1da63c96766a75d057fbe4a8993ed50e749a3002`; supplied develop base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Initial worktree is clean; no incoming changes to salvage.
- Inputs: supplied dispatch-context.json, prior result b02de7b, and prior
  failed check-3.log from job 98a1131. No check-*.log files exist in this job
  directory at initial inspection.
- Process the observed schema-fence test failure and required exact vulture
  scan, then assess all ten acceptance criteria. Do not enumerate new issues
  or PRs or change unrelated runtime behavior.
- Candidate edit scope: this validation note; the existing pg_learnings schema
  fence test if still broken; its inventory note if tests change; and
  quality/vulture-baseline.json only for observed reviewed scan findings.
  Read-only inspection includes the soak harness/profile/evidence, adjacent
  runtime/tests, CI gate implementations, repository instructions and ADRs.

## Assumptions / constraints

This is a writer repair, not a verifier-only assignment. Historical failure
and readiness claims are inputs, not proof. No exact RC image/configuration
has been supplied by this dispatch; do not relabel a host smoke run as a
production soak. Accepted ADRs retain Goal -> Graph -> Run -> NodeRun -> Attempt
as the sole execution authority. No GitHub mutations are permitted.

## Progress

- Starting head and clean worktree confirmed.
- Prior failure: schema test expected 21 statements but runtime emitted 24.
  Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  exits 0: 37 passed, 6 skipped. Current expected DDL already includes the
  three Gauntlet columns. The reported failure does not reproduce.
- Required `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  exits 0: 1322 reviewed identities, 1322 findings, zero unclassified.
  No evidence warrants a ledger amendment or deletion of retained symbols.
- Logs: `/tmp/860-ffa-schema.log`, `/tmp/860-ffa-vulture.log`.
- Prior result was BLOCKED, not promotion approval.

## Fresh validation and architecture review

All following commands exited 0:

- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -x -q`:
  88 passed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  27 passed.
- `uv run python scripts/check-suite-inventory.py`: all 17 suites match;
  31327 unique identities. No tests added or changed; no inventory delta.
- `uv run python` imported `scripts/soak/run_soak.py` with importlib and
  evaluated `docs/testing/soak/evidence/m3a-round109-shakedown.json` using
  `failed_promotion_checks`: exactly `sustain_duration`, `exact_rc_artifact`
  fail. Recorded duration is 420.05 seconds against 14400 minimum. This is
  fresh evaluator execution over historical evidence, NOT a new live soak.

Read accepted ADR-081226-a66b, ADR-081626-f383, ADR-082426-82c7 and ADR-085.
Canonical admission and physical execution remain distinct. The execution-fence
ADR explicitly does not define expiry takeover; this issue cannot introduce an
implicit competing reclaim authority. A unique schedule Run is not proof of
unique physical effects. Per-principal rate-limit keys do not imply shared
replica budgets: production middleware constructs its own InMemoryRateLimiter
and documents N-times aggregate allowance (rate_limit.py:32–37, 94–99).

Inspected the actual production Compose topology, load profile, promotion
checks, schema-fence implementation/test, and adjacent evaluator tests.
`preflight_artifact_check` (run_soak.py:744) unconditionally rejects host-process
artifact equivalence. Its regression tests exercise missing/null/preflight
artifact rejection even for synthetic four-hour evidence. No code, policy,
authorization path, ledger, or gate was changed.

## Acceptance assessment

| # | Criterion | Executed evidence / limitation |
| --- | --- | --- |
| 1 | Representative RC workload | Profile inspected; its remaining-gaps section lacks multiple users/Workspaces, Graph fan-out, successful tool/model work, Design/Canvas and background reconciliation. Full criterion UNVERIFIED. |
| 2 | At least two production replicas | Compose declares two services; historical JSON records two replicas. No current RC production run executed: UNVERIFIED. |
| 3 | Sustained saturation/reclaim/leak coverage | Evaluator rejects 420.05 seconds versus 14400 minimum; long-window behavior UNVERIFIED. |
| 4 | No duplicated physical work | Historical admission flags pass, but claim-probe Run is cancelled without execution per profile. Physical effects and Goal reconciliation UNVERIFIED. |
| 5 | Effective security/degradation across replica selection | 27 server tests passed. Production middleware has independent process-local budgets; six-path 429 probes do not prove replica-independent allowance. Full criterion UNVERIFIED. |
| 6 | Complete production metrics with thresholds | Historical JSON includes RSS/FD and checks; profile explicitly distinguishes driver-loop lag from application-loop lag. Complete production instrumentation UNVERIFIED. |
| 7 | Kill/restart during active physical work | Historical JSON reports SIGTERM drain/rejoin and zero nonterminal Runs. No live restart this round; physical fencing/recovery UNVERIFIED. |
| 8 | Long soak of exact promoted RC/config | UNMET: executed evaluator rejects both duration and artifact. Immutable designated RC image/configuration not supplied in assignment. |
| 9 | Findings filed/reclassified before promotion | Existing evidence records retained; final external disposition UNVERIFIED. GitHub mutations prohibited and not performed. |
| 10 | Machine/human evidence bound to promoted hashes | Historical records exist, but host-process artifact check fails. Exact promoted image/configuration evidence UNVERIFIED. |

## Disposition / next action

**BLOCKED.** The stale schema-test failure and requested ledger repair have no
current failing evidence. Only this validation/handoff file changes. This is
not a completed soak, implementation approval, or integration approval.

Release owner must identify the immutable RC/configuration and applicable
production workload. Then execute a production-artifact runner for at least
four hours with missing physical-effect/recovery and production-metric probes,
and resolve the replica-selection budget gap. Repeating this preflight longer
cannot pass its artifact gate. Do not repeatedly redispatch the already-passing
schema assertion or ledger scan as the repair for these acceptance blockers.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 exact-RC production workload and soak"}`.
Local validation is complete; the sole assigned issue remains blocked.
