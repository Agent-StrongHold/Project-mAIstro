# Issue 860 repair checkpoint — job 85cf2d7c

## Frozen scope

Only issue #860 on branch `auto-860`, starting at
`4ab542257ef673f49ca5fae3b3aa359bc737104e`, with supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7` (both locally resolved).
Initial worktree is clean. No sync conflict exists. No remote mutation is allowed.

Process the explicit vulture CI-repair request and validate the existing soak
acceptance evidence. Inspection scope: repository instructions, relevant execution
ADRs, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, the soak
profile, production rate-limit wiring, the named prior result/failure log, and
CI gate definitions. Edit scope: this report and, only if fresh findings justify
it, the reviewed vulture ledger/dead identities and directly adjacent tests with
an inventory note. No unrelated issue/PR processing or historical report sweep.

The current job directory contains no `check-*.log` files. The supplied prior
result says BLOCKED; it is evidence to recheck, not verification. The dispatch
snapshot contains the issue's ten acceptance criteria. Ambiguity: no exact RC
artifact/configuration or target endpoints are supplied in the lane brief;
proceed with local validation, without presenting preflight as release evidence.

## Results

Fresh results (all commands use this worktree):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0; 1323 reviewed identities and 1323 findings, zero unclassified/never-allowlist findings. No unbanked identity exists to repair; do not manufacture a ledger amendment. The gate selected base `4aa68edc0b6b` automatically, not the supplied develop base.
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: exit 0, **103 passed, 6 skipped**. Includes production-middleware replica-allowance reproduction, preflight promotion refusal, real child-process resource sampling, schema fence ordering, and HTTP concurrency backpressure.

The supplied historical `98a113.../check-3.log` fails because its schema-fence
expectation lists 21 DDL statements while production executes 24. The current
test already includes all three validation audit columns, and passes in the
fresh run above. This failure is not reproducible at the assigned head.
No test changes or inventory delta are warranted by these results.

Local logs: `/tmp/860-85cf-vulture.log`, `/tmp/860-85cf-tests.log`.
- `uv run python scripts/check-doc-links.py`: exit 0; 2635 Markdown files scanned, zero broken relative links.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`: exit 0; 37 passed, 6 skipped. All six skips require `MAISTRO_TEST_PG_DSN` pointing at a migrated PostgreSQL database. They are not counted as production concurrency proof.
- `git diff --check`: exit 0 before final report completion.

## Architecture and reachable behavior

Read repository `AGENTS.md` and ADR-081, ADR-085, ADR-081226-a66b,
ADR-081626-f383, ADR-082426-82c7. ADR-081 is **Proposed**, not an accepted
waiver of issue acceptance. Accepted lifecycle/fencing/occurrence decisions
keep authority in the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
model. Admission uniqueness cannot stand in for physical Attempt fencing.
ADR-085's per-principal rate policy does not establish a distributed limiter.
No new scheduler, store, event, or authorization authority is introduced.

- `scripts/soak/run_soak.py:730` returns `exact_rc_artifact.ok=false`;
  line 1552 wires it into actual run evidence. The CLI test executes the
  rejection of missing/null/preflight artifact records even at four hours.
- `scripts/soak/run_soak.py:1231` starts host-process replicas. This is not
  deployment of the exact promoted Compose artifact.
- `scripts/soak/run_soak.py:1044` cancels the schedule probe's queued Run via
  the canonical store; its docstring explicitly says nothing executes it.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the
  production `RateLimitMiddleware`. Its constructor at `api/rate_limit.py:93`
  creates an independent `InMemoryRateLimiter` per middleware instance.
  `tests/test_soak_promotion_gates.py:439` freshly reproduces `[200,200,429]`
  on each of two instances for the same identity, both authenticated and
  unauthenticated. The probes prove local enforcement, not replica-selection
  non-bypass of a shared principal allowance.
- `scripts/soak/run_soak.py:1410` measures the **driver's** event-loop lag,
  not the applications'. Existing resource-sampler tests exercise a real
  child process, but cannot establish long-running production telemetry.

## Acceptance disposition

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md` explicitly identifies one-key preflight gaps: concurrent Workspaces/users, Graph fan-out, successful tools/models, Design/Canvas, Goal/background reconciliation. No selected RC profile supplied in the lane brief. |
| At least two deployed replicas | **UNVERIFIED** for RC. Host-process boot path inspected; two-instance middleware tests passed, not deployment evidence. |
| Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED**. No sustained RC load was run. Unit resource sampling is not a lease/retry/leak soak. |
| Physical-work uniqueness and Goal reconciliation | **UNVERIFIED**. Inspected schedule probe only races admission and then cancels its Run. No physical completion/reclaim proof. |
| Rate/security/degraded non-bypass | **UNVERIFIED** overall. Fresh production-middleware test demonstrates independent per-replica allowances. Backpressure tests pass, but do not establish security/degraded behavior under representative production concurrency. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Profile has thresholds and partial sampler tests pass; application event-loop lag and sustained production pool/queue/worker observations remain missing. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED**. No active RC work killed/restarted this round. Replica rejoin and terminal counts cannot establish physical-work fencing. |
| Long unchanged exact-RC soak | **UNVERIFIED**. Runner intentionally rejects preflight as exact RC; minimum is 14400 seconds. No promotion-grade run was executed. |
| Findings filed/reclassified before promotion | Local findings recorded here; external disposition **UNVERIFIED**. GitHub mutation prohibited. No new load findings were generated. |
| Hash-bound machine/human RC evidence | **UNVERIFIED**. This is a validation report, not a new RC evidence bundle. Old artifacts cannot validate the current head/configuration. |

## Handoff

**BLOCKED for issue acceptance**, despite passing focused CI validation. The
reported vulture debt and old schema assertion failure do not reproduce. No
source or ledger edit is justified; only this evidence report changed, with no
test additions and therefore no inventory delta.

To unblock: select the immutable RC application/database images, normalized
runtime/Compose configuration, representative workload scope and test target;
provide an exact-artifact runner with physical-work/Goal recovery checks and
complete telemetry; resolve or explicitly govern the replica-local budget
semantics without weakening #860; execute the unchanged artifact for at least
four hours and publish hash-bound machine/human evidence. This round does not
claim those prerequisites were satisfied by historical notes or short probes.
Do not repeat a cosmetic ledger repair or another short host preflight as a
substitute. No remote fetch, push, issue comment, or integration was performed.

Progress: checked 1 assigned item; done 0 acceptance-complete items; skipped 0;
errors 0 validation commands; next: supply the RC prerequisites above. Local
commit of this report is the writer handoff, not release approval.
