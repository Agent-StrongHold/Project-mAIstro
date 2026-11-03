# Issue #860 — repair checkpoint (af0395b3)

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`853ed9f7d16dabaf96c13d0904aed5deba3c116d`, supplied base
`2f56be40ad241262b0384ab0b97834ebd37fe4d7`.
Initial worktree clean; no incoming uncommitted work to salvage.
No GitHub mutations or new issue/PR enumeration.

Files selected for investigation: repository instructions and relevant ADRs;
`packages/maistro-core/src/maistro/persistence/pg_learnings.py` and
`packages/maistro-core/tests/persistence/test_pg_learnings.py`;
`quality/vulture-baseline.json` and `scripts/check-vulture-baseline.py`;
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`packages/maistro-server/src/maistro_server/api/rate_limit.py`,
`packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`,
`docs/testing/soak/m3a-load-profile.md`, and relevant inventory notes.
Only evidence-backed repairs to this scope will be made.

## Initial evidence / ambiguity

The current job directory contains no `check-*.log` files. The explicitly
supplied prior `98a11313167b41a98a420abfda80c292/check-3.log` reports the
schema-fence test expecting 21 statements but observing 24. This is historical
evidence, not proof that the assigned head still fails. Reproduce first.
The prior result reports unresolved exact-RC soak acceptance. Assume this is a
focused repair round, not permission to invent an RC identity or new runtime
execution/authorization authority. Revalidate rather than inherit its verdict.

## Reproduced checks

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped** (PostgreSQL-dependent cases). The reported 21-vs-24
  failure is already repaired at this head: the test independently enumerates
  all 24 DDL statements, including three Gauntlet audit columns.
- Required exact vulture command: **passed**, 1,322 findings / 1,322 reviewed
  identities, zero unclassified. No retained unbanked identity exists to amend;
  changing the ledger would be unsupported. Gate chose merge base `ab8b3737fa64`,
  not the supplied comparison base; no refs or gate arguments were changed.

Logs: current job directory, `worker-pg-learnings.log`, `worker-vulture.log`.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **73 passed**, including both identity cases that reproduce independent
  rate-limit allowances after selecting the second replica.
- Executed evaluator reproduction: replacing `exact_rc_artifact` with
  `{"ok": "false"}` returns no failed checks; replacing `graceful_drain` with
  `{}` also returns no failed checks. These malformed records must not pass.
  Repair is confined to the existing evidence evaluator and its CLI regression
  tests, not a new execution or authorization path.

ADR reconciliation: accepted ADR-081226-69ee preserves Graph/Run/NodeRun/Attempt
ownership; accepted ADR-081626-f383 does not authorize implicit lease-expiry
reclaim. Accepted ADR-085 requires per-principal rate limiting but supplies no
new distributed-store authority. ADR-081 is Proposed, not an accepted waiver.
No schema/scheduler/rate-limit architecture is changed to manufacture soak
acceptance.

## Focused repair and regression proof

`scripts/soak/run_soak.py` now accepts only literal boolean `true` as a pass
and requires an explicit boolean `graceful_drain.required`. Missing or malformed
flags cannot obtain the explicit SIGKILL drain exemption. Valid existing boolean
records remain unchanged. No gate is weakened.

- Before the fix: new CLI regression cases **12 failed** (`worker-regression-red.log`).
- After the fix: soak plus server backpressure suites **85 passed**
  (`worker-soak-after.log`). Existing positive paths and both real middleware
  replica-selection counterexamples still pass.
- `uv run ruff check .`: **passed** (`worker-ruff.log`).
- `uv run ruff format --check .`: **passed**, 3,301 files (`worker-format.log`).
- Inventory delta: `tests/: +12`, recorded in
  `docs/testing/inventory-notes/860-soak-strict-evidence-booleans.md`.

## Final validation

- `uv run pytest packages/maistro-server/tests -x -q`: **558 passed, 8 skipped**,
  22 deprecation warnings (`worker-server.log`). No skip is counted as proof.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: **passed**,
  5,303 collected identities, zero duplicate evidence (`worker-inventory.log`).
- `uv run python scripts/check-doc-links.py`: **passed**, 3,031 Markdown files,
  zero broken relative links (`worker-doc-links.log`).
- `uv run python scripts/soak/run_soak.py --help`: **passed**
  (`worker-soak-help.log`); CLI availability is not a live soak.
- `git diff --check`: **passed**.

All commands ran in the assigned worktree with explicit long timeouts. Logs
are in `/home/dev/maistro/jobs/af0395b3ff6946ac9209c83cad285144/`.

## Acceptance assessment (issue body order)

1. **Representative RC load profile — UNVERIFIED.** Read
   `m3a-load-profile.md`: it explicitly lacks a user/Workspace population,
   Graph fan-out, successful model/tool work and Design/Canvas coverage.
   No selected RC configuration was validated in this round to justify exclusions.
2. **Two supported production replicas — UNVERIFIED.** Executed ASGI tests
   instantiate two real production middleware instances, not two production
   application processes/images. They cannot satisfy this criterion.
3. **Sustained saturation/reclaim/leak observation — UNVERIFIED.** No live
   sustained run performed. Unit checks and historical short runs are not a soak.
4. **No duplicate physical work — UNVERIFIED.** Read the reachable schedule
   probe in `run_soak.py`: it races admission, then cancels the queued probe Run
   through `PgRunStore`; no physical Attempt executes. Admission uniqueness is
   not execution uniqueness or Goal reconciliation proof.
5. **Replica-independent rate/security/degraded enforcement — NOT PROVEN.**
   Both executed `test_replica_selection_has_an_independent_production_allowance`
   cases observe `[200, 200, 429]` on each middleware instance for the same
   identity. Production `RateLimitMiddleware.__init__` constructs a separate
   `InMemoryRateLimiter`. The counterexample disproves a cluster-wide budget;
   independent per-replica limits are documented behavior, not a soak waiver.
   Full security/degraded-path coverage remains UNVERIFIED. Server backpressure
   tests do verify 429/Retry-After and subsequent admission after a slot frees.
6. **Production telemetry with thresholds — UNVERIFIED.** Sampler tests pass,
   but the profile explicitly says driver-loop lag is not application-loop lag;
   no new production telemetry series was recorded.
7. **Active-work kill/restart drain/fencing/recovery — UNVERIFIED.** Evidence
   validation rejects malformed drain records after this repair. That proves
   neither recovery nor physical work continuity on a killed production replica.
8. **Long exact-RC soak — UNVERIFIED.** Executed
   `test_four_hour_preflight_cannot_pass_cli` proves missing/null/preflight
   artifact records fail. `preflight_artifact_check()` always rejects this
   driver's host-uvicorn topology. Running it longer cannot meet this criterion.
9. **Findings disposition before promotion — UNVERIFIED overall.** This round's
   evidence-evaluator defect belongs to the M3 release-evidence invariant and
   is repaired with red/green tests here. Runtime replica-limit and recovery
   gaps remain explicit; no GitHub filing/reclassification or closure was
   performed, per the lane prohibition.
10. **Machine/human evidence bound to exact hashes — UNVERIFIED at production
    grade.** This report binds local regression validation to the assigned
    starting head and the following local commit. It is not a hash-bound
    production image/config soak pack. The repaired evaluator is not an
    authenticity checker and cannot turn synthetic evidence into a real soak.

## Handoff

Changed files: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`docs/testing/inventory-notes/860-soak-strict-evidence-booleans.md`, and this
report. No quality ledger/grant or execution authority changed. The inherited
branch history is preserved; this round does not certify its unrelated diffs.

One assigned issue checked; focused repair done; issue acceptance unfinished.
No stale schema-fence or vulture repair was fabricated. Next work requires a
selected immutable RC image/configuration, a representative production-path
workload and telemetry, and resolution/disposition of the observed runtime
limits before the at-least-four-hour soak can establish acceptance. Do not
repeat the host preflight or this unit-validation loop as promotion evidence.
Verdict: **NEEDS-REPAIR**, not integration approval.

