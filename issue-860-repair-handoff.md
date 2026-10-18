# Issue #860 repair checkpoint

Scope frozen: issue #860 only, branch auto-860, starting HEAD
8c927c3d4dd562c17c770df41ed50b7c21b1b6cb, base
ab8b3737fa64f8d840f421ef87ca506c509444ff. No GitHub mutations.

Assigned item: reproduce the exact vulture gate and review retained identities;
validate existing soak acceptance without claiming local probes are production
release evidence. Candidate edits are quality/vulture-baseline.json (explicit
lane exception), evidence-backed implicated source only, and this handoff.
No new tests planned unless an actual behavioral repair is warranted.

Initial evidence: clean worktree, exact starting HEAD confirmed. Current job
309ff225f5c04e8ea8ffed9d66d16324 has no check-*.log files. Prior result
9c8273ba385542e2ba389fac879b5868 reports BLOCKED; claims are not yet verified.
The issue has ten acceptance criteria including a long exact-RC production
soak. Assumption: this repair does not authorize deploying an unspecified RC,
changing runtime architecture, or treating historical smoke data as a soak.

Checkpoint 1: exact vulture command passed (1322 reviewed identities, 1322
findings, zero unclassified/never-allowlist). No ledger amendment is warranted.
The cited historical check-3.log is a pytest failure, not a scanner failure:
`test_ensure_schema_fences_ddl_behind_advisory_lock` observed 24 DDL calls
against 21 expected. Reviewing the current implementation/test before deciding
whether it still needs repair. Accepted ADR-081226-a66b preserves canonical
Run/NodeRun/Attempt authority; ADR-082426-82c7 distinguishes admission uniqueness
from physical execution. No alternate execution mechanism will be introduced.

Checkpoint 2: historical pytest failure does not reproduce. Current test already
lists the three Gauntlet audit columns independently (lines 169–173). The
production upgrade executes those columns under the same advisory transaction
(lines 218–226). No source/test change is justified by that stale failure.
Executed with 1200-second timeout:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped (PostgreSQL integration cases not established).
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  1 passed.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  80 passed. Includes real production middleware instances showing independent
  per-replica allowances, not a shared principal budget.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.

No tests added or changed; inventory delta is zero, no inventory amendment needed.
Accepted ADR-083026-a91e requires unmeasured metrics to remain absent; driver
loop lag cannot stand in for application loop latency.

## Acceptance review (current attempt)

1. **Representative release profile — UNVERIFIED.** Read
   `docs/testing/soak/m3a-load-profile.md`: the current preflight omits concurrent
   users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas,
   and sustained Goal reconciliation. The document explicitly calls these gaps
   blockers rather than waivers.
2. **Two production replicas — UNVERIFIED.** Existing ASGI tests instantiate two
   middleware instances, not the production deployment. No production topology
   was deployed during this attempt.
3. **Sustained load — UNVERIFIED.** Executed current evaluator against the frozen
   historical `docs/testing/soak/evidence/m3a-round5-final.json`: 90.17 seconds
   versus the required 14400 seconds; `sustain_duration` rejected. This is a
   re-evaluation of historical data, not a new live measurement.
4. **Physical-work uniqueness — UNVERIFIED.**
   `scripts/soak/run_soak.py:1070` explains that the schedule race only admits
   work and cancels its queued Run without execution. Admission deduplication
   is not evidence of physical Attempt fencing. Accepted lifecycle ADRs remain
   authoritative; no extra scheduler or execution authority added.
5. **Replica-independent rate/security/degraded enforcement — UNVERIFIED,
   contrary rate-budget evidence reproduced.** Production middleware creates
   an `InMemoryRateLimiter` per instance (`rate_limit.py:94`), wired by
   `packages/maistro-server/src/maistro_server/main.py:648`.
   `tests/test_soak_promotion_gates.py:439` passes for both authenticated and
   unauthenticated callers: exhausting one replica leaves another allowance.
   ADR-085 requires principal identity but does not establish a shared-store
   implementation. The documented local limit is not treated as satisfying
   #860's stronger replica-selection criterion; no authorization bypass added.
6. **Complete telemetry and thresholds — UNVERIFIED.** Process-group sampler
   tests passed, including a real uv child. They do not measure production
   application event-loop lag, full worker/cgroup resources, pool saturation,
   lease recovery or long-term growth.
7. **Active-work kill/restart fencing/recovery — UNVERIFIED.** No new kill/restart
   experiment performed. Healthy process rejoin and terminal Run counts are
   insufficient to prove absence of lost or duplicated physical work.
8. **Long exact-RC soak — UNVERIFIED.** Executed `preflight_artifact_check()`:
   returns `ok=False`, topology `host-uvicorn-preflight`. Historical evidence
   evaluation rejects `exact_rc_artifact`; three parametrized CLI tests confirm
   four-hour synthetic data cannot bypass missing/null/preflight identity.
9. **Complete findings disposition — UNVERIFIED.** Existing findings are recorded
   locally, but complete release disposition is not established. No GitHub
   mutation was performed or authorized.
10. **Promoted-hash-bound machine/human evidence — UNVERIFIED.** Historical JSON
    carries another commit and no current promoted application image identity.
    No immutable selected RC/configuration or new production soak was supplied.

Additional executed validation: an `uv run python` import/evaluator probe asserts
that the historical round-5 JSON fails duration and artifact gates. The actual
failed checks are `rate_limit_enforced`, `sustain_duration`, `exact_rc_artifact`.
`git diff --check` passed. No claim is made that all archived evidence was
re-enumerated or verified.

## Disposition / next prerequisites

BLOCKED for issue acceptance, not a reproduced vulture or schema-test failure.
Only this handoff is changed; production code, tests, inventory, ledgers, grants
and gates are unchanged. A speculative ledger amendment would falsify a passing
1322-identity scan, so the explicit lane permission was not exercised.

Next: provide the selected immutable production RC/configuration and an approved
representative workload covering the missing surfaces; resolve the observed
replica-budget mismatch at its owning invariant, then perform a new >=4-hour
production run with physical-work/recovery correlation and complete telemetry.
Do not repeat local preflight tests as a substitute for that evidence. No new
items are being started. Summary: checked 1 assigned issue, done 0 acceptance
completions, skipped 0 issues, errors 0 validation-command failures; next is the
blocked production-evidence work above. The ten criteria remain unproven.

