# Issue #860 — bounded repair validation (852444ee)

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `0365d5b49e0ecbcac395f40652d0d5b470c96cf3`; assigned base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Clean incoming worktree; no salvage needed. No current-job `check-*.log`
  files present in the supplied job-directory snapshot.
- Inspect the supplied dispatch context, prior result and prior `check-3.log`.
- Validate the reported schema-fence regression in
  `packages/maistro-core/{src/maistro/persistence/pg_learnings.py,tests/persistence/test_pg_learnings.py}`.
- Run the explicit Vulture identity gate; edit `quality/vulture-baseline.json`
  only if actual retained/unbanked identities require it.
- Review existing `scripts/soak/run_soak.py`, promotion-gate tests, server
  concurrency/rate-limit paths, load profile and selected existing evidence.
- Run focused validation, record acceptance gaps here, commit locally.
  No remote mutations, new execution authority, grant changes or new soak claims.

## Initial evidence

The supplied prior check failed because its schema-fence test expected 21 DDL
statements while production executed 24. This is historical evidence, not proof
that the assigned HEAD still fails. The prior worker reported BLOCKED for missing
exact-RC sustained production evidence. This round will verify rather than assume
those conclusions. No develop-sync conflict exists in the incoming tree.

## Results

- Fresh explicit Vulture scan passed: 1322 reviewed identities, 1322 findings,
  zero unclassified. No ledger amendment is justified.
- Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. The current independent expected-DDL list already
  includes all three Gauntlet audit columns; the historical failure is resolved.
- No code or test repair is warranted by either reported CI finding.
- `uv run ruff check .`: exit 0, all checks passed.
- `uv run ruff format --check .`: exit 0, 3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -x -q`:
  exit 0, 88 passed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  exit 0, 27 passed.
- `uv run python scripts/check-suite-inventory.py`: exit 0, all 17 suites
  match; 31327 unique identities, zero duplicates. No tests changed or added;
  no inventory delta is required.
- `uv run python` loaded `scripts/soak/run_soak.py` via importlib and called
  `failed_promotion_checks` on the existing
  `docs/testing/soak/evidence/m3a-round109-shakedown.json`. Result:
  `['sustain_duration', 'exact_rc_artifact']`. Observed duration 420.05 seconds,
  minimum 14400; artifact topology `host-uvicorn-preflight`, `ok: false`.
  This is fresh evaluation of historical data, not a newly executed live soak.

## Architecture and acceptance reconciliation

Read accepted ADR-081226-a66b, ADR-081626-f383, ADR-082426-82c7 and ADR-085.
The sole execution hierarchy remains Goal -> Graph -> Run -> NodeRun -> Attempt.
An occurrence admission claim does not establish uniqueness of physical work.
The execution-lease ADR explicitly does not yet define expiry takeover; the
issue's reclaim requirement cannot authorize a competing recovery mechanism.
ADR-085's principal identity requirement does not itself make budgets shared.
Production `RateLimitMiddleware.__init__` creates an `InMemoryRateLimiter` per
process (`packages/maistro-server/src/maistro_server/api/rate_limit.py:94`),
and lines 32–37 explicitly document N-times aggregate allowance.

Inspected the supported two-replica production Compose topology, the preflight
profile, production schema-fence implementation and its independent DDL-list
test, promotion evaluator and adjacent negative-path tests. The evaluator's
`preflight_artifact_check` at `scripts/soak/run_soak.py:744` deliberately rejects
host-process equivalence. The CLI regression tests reject missing, null and
preflight artifact records even with synthetic four-hour evidence. These are
meaningful fail-closed checks, not proof of production soak completion.

The supplied dispatch issue body is the acceptance source. Its immutable RC
image/configuration is not designated in the lane assignment. Assumption:
this worker must not invent a promoted artifact or relabel preflight results.

| # | Acceptance criterion | Fresh evidence / assessment |
| --- | --- | --- |
| 1 | Representative users/Workspaces and workload mix | Profile reviewed; remaining gaps explicitly include multiple users, Graph fan-out, successful tool/model work, Design/Canvas and background reconciliation. UNVERIFIED. |
| 2 | At least two production replicas | Compose defines two replicas; this round executed no live production RC deployment. UNVERIFIED. |
| 3 | Sustained saturation, reclaim, retry and leaks | Existing evidence fails duration (420.05 < 14400 seconds); production long-window behavior UNVERIFIED. |
| 4 | No duplicate physical work across replicas | Admission/probe tests are insufficient; profile says schedule probe Run is cancelled without executing it. Physical effects and Goal reconciliation UNVERIFIED. |
| 5 | Security/degradation cannot be bypassed by replica selection | 27 server tests pass; process-local allowance multiplies across replicas. Full production requirement UNVERIFIED, not waived by six burst probes. |
| 6 | Full metrics and explicit thresholds | Existing profile distinguishes driver-loop lag from application-loop lag and process-group measurements from detached workers/cgroups. Complete production instrumentation UNVERIFIED. |
| 7 | Kill/restart during active work with drain/fencing/recovery | Evaluator tests reject missing drain evidence, but no active physical-work restart was executed this round. UNVERIFIED. |
| 8 | Long-running exact-RC/config soak | Executed evaluator rejects both duration and artifact. UNMET; no designated immutable RC/config supplied. |
| 9 | Findings disposition before promotion | Existing records preserved; final disposition UNVERIFIED. No GitHub mutations performed. |
| 10 | Published machine/human evidence tied to promoted hashes | Historical records exist but fail artifact validation. Exact promoted-image/configuration evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not integration approval. Only this validation note changed.
No production code, tests, inventory counts, ledger, authorization or gate changed.
No speculative repair is justified by the supplied historical CI failure.

Next: release owner must designate the immutable RC and configuration, settle
representative workload scope, and provide a production-artifact execution path
with physical-work/recovery and complete application metrics. Execute at least
the profile's four-hour window and resolve the replica-selection budget gap.
Running the existing host preflight longer cannot satisfy its artifact gate.
Do not redispatch the already-passing schema-fence assertion or Vulture ledger
as though either supplies the missing promotion evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 exact-RC production soak and unresolved acceptance evidence"}`.
Local focused validation completed; the assigned issue remains blocked.
