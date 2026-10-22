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

## Round 860 current-head revalidation (328c80121b99)

Starting HEAD and clean status were confirmed at
`328c80121b990bc336ad5be2c17db29f38c09864`; base is
`c29e0ea7094198095c107e3583dbfd5e50009a5d`. No `check-*.log` files were
present in the assigned job directory. The supplied prior result says the work
ended at this same HEAD and was BLOCKED; its claims were checked against live
tree/evidence rather than accepted as proof. The issue's ten acceptance items
were frozen from the supplied dispatch snapshot; no other issue/PR is in scope.

Executed the exact vulture CI command:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
PASS: 1315 reviewed identities, 1315 findings, `unclassified: 0`,
`never_allowlist: 0`. No ledger edit is justified.

Re-evaluated `docs/testing/soak/evidence/m3a-round109-shakedown.json` with the
current `failed_promotion_checks()` and called current
`preflight_artifact_check()`. Recorded evidence is clean at historical head
`5a59c724a20ef1241d57c048df90758f2c2e1e25`, but is only 420.05 seconds; the
current evaluator returns failed checks `sustain_duration` and
`exact_rc_artifact`, and current preflight explicitly returns
`ok=false, topology=host-uvicorn-preflight`. This is historical shakedown data,
not an RC soak. `docs/testing/soak/m3a-load-profile.md` further explicitly
states the current workload excludes concurrent users/Workspaces, Graph/node
fan-out, successful model/tool calls, Design/Canvas, and sustained Goal
reconciliation; it also disclaims physical Attempt fencing and application
loop/cgroup telemetry.

Thus the ten issue criteria remain UNVERIFIED for promotion: representative
profile; two replicas of the selected production artifact; sustained resource,
queue and recovery load; physical-work fencing/reconciliation; replica-selection
security behavior; complete telemetry; active-work kill/restart recovery; >=4h
exact-RC soak; findings disposition; and machine+human evidence tied to the
promoted artifact/config hashes. The historical shakedown's successful
admission/schedule claims and resource values do not close these exact-RC gaps.
Accepted ADR-081226-a66b retains the Run→NodeRun→Attempt lifecycle authority;
ADR-082426-82c7 makes the schedule occurrence the canonical Run claim. No
competing execution/scheduler authority is introduced.

No tests were added, so no suite-inventory note is required. No production soak
was possible without an identified immutable RC/configuration and production
runner. Only this handoff is amended; issue remains BLOCKED pending those inputs
and a fresh >=4h exact-artifact measurement. The assigned job directory contains
no deterministic check logs, as noted above.

