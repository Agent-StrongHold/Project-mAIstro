# Issue #860 — validation and blocked acceptance handoff (93d4ea10)

## Scope and checkpoint

Processed only issue #860 on `auto-860`; starting HEAD was
`17fcc18b1794ad0075c469f760c3aa04bdec9362`. The assigned job directory had no
`check-*.log` or prior `result.json`; no verifier logs were treated as evidence.
The prior-result path supplied in the prompt is absent. Fetched `origin/develop`
(`c2d7209f1dbc1039e8ca9d99444b88ded3bbe26b`) and merged it cleanly because the
branch was behind those two commits. The merge contains unrelated develop work
only and is committed separately by Git. No pre-existing worktree changes were
present. No GitHub actions were performed.

Read the accepted ADRs for the canonical `Goal -> Graph -> Run -> NodeRun ->
Attempt` lifecycle, ExecutionRuntime mechanics boundary, and Attempt lease
fencing. They do not permit treating admissions as physical execution or
introducing another scheduler/execution authority. The deployment ADR remains
reference configuration, not a selected RC.

## Fresh validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1326 reviewed identities, 0 unclassified, 0 never-allowlist; baseline resolved to `c2d7209f1dbc`.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` — PASS: 111 passed in 3.89s.
- `git diff --check` — PASS after develop merge.

These checks do not constitute a production soak. No tests were added or changed,
so suite inventory has no delta and no inventory note is warranted. No ledger
amendment is supported by the actual scanner result.

## Acceptance review (all ten criteria)

1. **Representative RC profile:** UNVERIFIED. `docs/testing/soak/m3a-load-profile.md`
   says it omits concurrent users/Workspaces, Graph fan-out, successful
   tool/model calls, Design/Canvas, and Goal/background reconciliation; RC
   applicability is not designated.
2. **Two application replicas:** UNVERIFIED. No exact RC was deployed in this
   round; tests of independent middleware instances are not deployed replicas.
3. **Sustained saturation, queue growth, reclaim/retry, leak and shutdown
   observations:** UNVERIFIED. No sustained production-topology load was run.
4. **No duplicate physical work across schedules/tasks/Runs/Attempts and Goal
   reconciliation:** UNVERIFIED. Admission/receipt behavior does not prove
   physical Attempt effects or recovery.
5. **Replica-selection-resistant rate/security/degraded enforcement:**
   acceptance is not established; the production middleware regression in
   `tests/test_soak_promotion_gates.py` demonstrates independent local
   allowances across instances. A shared aggregate rate budget is not proven.
6. **Complete telemetry and explicit thresholds:** UNVERIFIED at RC grade. The
   profile distinguishes driver-loop lag from application-loop lag and lists
   missing production worker/pool/reclaim/long-window observations.
7. **Active-work replica kill/restart, drain/fencing/recovery:** UNVERIFIED. No
   production restart or physical recovery observation was performed.
8. **Long exact-RC artifact/configuration soak:** UNVERIFIED. The profile states
   its host-process driver cannot prove promoted Compose artifact equivalence;
   no immutable RC/configuration evidence was supplied.
9. **Earliest-broken-invariant classification:** UNVERIFIED for representative
   production findings; no such new load findings were generated.
10. **Machine/human evidence bound to exact hashes:** UNVERIFIED for a qualifying
    production soak. Source validation is not deployment-bound evidence.

## Result and next step

**BLOCKED for acceptance/promotion.** The Vulture gate and focused tests pass,
but neither repairs nor evidence can be inferred from the absent job logs. No
production code, tests, inventory, ratchet, or grant was changed. The actual
remaining work requires an owner-designated immutable RC and normalized config,
resolution of the aggregate rate-limit mismatch, and the full representative,
long-window production soak with physical Attempt/recovery correlation and
hash-bound machine/human evidence. Repeating local preflight/unit checks cannot
meet those requirements.

Progress: checked 1 assigned issue; acceptance-complete 0; skipped 0; fresh
validation command errors 0. This local commit is a handoff, not integration or
promotion approval.
