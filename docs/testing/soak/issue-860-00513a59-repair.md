# Issue #860 repair checkpoint — job 00513a59

## Frozen scope

- Issue #860 only; branch `auto-860`, clean starting head
  `011e9c2b5b900e9a25ec6509bc7e4e5828b8925f`.
- Supplied base `ac69535ef165ded3ca82cd3428728569de3251fa` resolves.
- Inspect supplied dispatch and prior result/log; inspect soak runner, adjacent
  tests, applicable ADRs and quality-gate workflow.
- Candidate implementation changes limited to actual #860 findings in
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, and
  `quality/vulture-baseline.json` (only if fresh scanner evidence warrants it).
  Any new tests require a corresponding inventory note.
- This report records fresh validation. No other issues/PRs will be processed.

## Initial observations

Current job directory contains no `check-*.log` files. Prior result reports
BLOCKED, not production acceptance. Those claims will not substitute for fresh
checks. The supplied base comparison includes substantial inherited unrelated
history; it is not authorization to alter that history. No sync conflict or
uncommitted work is present. No GitHub mutation, gate weakening, alternate
execution/authorization authority or speculative ledger edits are permitted.

## Fresh gate result

Requested exact Vulture command passed: 1323 findings, 1323 reviewed identities,
zero unclassified and zero never-allowlist. No ledger amendment is warranted.
The default comparison resolved baseline `3c761d14db94`. Re-running with
`RATCHET_BASE_REV=ac69535ef165ded3ca82cd3428728569de3251fa` also passed,
reporting the same resolved baseline (not a direct comparison to the supplied
base). Neither invocation found identities requiring repair.
Historical `98a11313/check-3.log` is a schema test failure (24 DDL statements
versus 21 expected), not a Vulture failure. It did not reproduce: the current
test independently enumerates all 24 statements, including the three audit
columns at `test_pg_learnings.py:175`. Production takes the advisory lock before
DDL in `pg_learnings.py:215`.

Ambiguity: mixed verifier/writer wording is resolved as writer mode by the
explicit repair assignment and mandatory local commit. No live RC artifact or
configuration is designated in the issue body; a host-process shakedown will
not be represented as a production soak.

## Executed validation

All validation commands used a 1200-second timeout and exited 0:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  (also repeated with the explicit `RATCHET_BASE_REV` above): 1323 reviewed
  identities / 1323 findings; no debt amendment justified.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3277 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  **118 passed, 6 skipped**, 2.88 seconds. Skips are not live-DB evidence.
- `uv run python scripts/check-doc-links.py`: 2697 markdown files, no broken
  relative links (before finalizing this report).

The initially attempted `maistro_server/middleware/rate_limit.py` path was not
found; skipped. The actual module imported by the regression is
`packages/maistro-server/src/maistro_server/api/rate_limit.py`, which was read.

## Architecture and acceptance

Read repository instructions, the documentation authority map, ADR-062,
ADR-082826-b601 and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The retired `run_graph` entrypoint is not an execution authority. Admission
uniqueness is not physical execution uniqueness. Principal-keyed rate limiting
in ADR-085 does not prove shared cluster allowance; #860's replica-selection
criterion is not waived by the documented process-local implementation.

| #860 acceptance criterion | Fresh disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md:171` lists missing users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and reconciliation workloads. |
| At least two production application replicas | **UNVERIFIED**. Executed ASGI and boot-contract tests are not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | **UNVERIFIED**. No long-running production observations were collected. |
| Physical-work deduplication and Goal reconciliation | **UNVERIFIED**. The profile's schedule probe cancels a queued Run without physical execution; receipt identity tests cannot establish Attempt fencing. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED** for production acceptance, with contrary evidence for a shared allowance. Executed `tests/test_soak_promotion_gates.py:439` confirms the same identity receives 200/200/429 independently on two production middleware instances. `api/rate_limit.py:33` documents N-times aggregate allowance. |
| Required telemetry and explicit thresholds | **UNVERIFIED**. Partial profile thresholds exist, but application-loop latency, saturation/reclaim and long-window observations are missing; driver-loop lag is not application-loop lag. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**. No production physical-work recovery was exercised. |
| Long-running exact RC artifact/configuration | **UNVERIFIED**. `scripts/soak/run_soak.py:744` unconditionally rejects the host-process topology. Promotion-gate tests passed, preserving that rejection. No immutable RC artifact/configuration is designated in the assignment. |
| Findings filed/reclassified before promotion | **UNVERIFIED**. No live-load findings generated or remote filing performed; GitHub mutations are prohibited. |
| Human/machine evidence tied to exact image/package/commit/config hashes | **UNVERIFIED**. This report is source-validation evidence, not a production soak bundle. |

## Handoff

**BLOCKED** on production acceptance, not on the requested Vulture gate or the
historical schema failure. Only this report changes; no source, ledger, tests,
inventory, execution authority or authorization path changes. No new tests means
no inventory delta. Existing branch work is preserved.

Next action requires a designated immutable RC image/configuration, completed
representative workload and production telemetry, resolved replica-selection
semantics, then a >=4-hour exact-RC soak with active-work recovery and physical
fencing evidence. Repeating the same CI-repair dispatch without those changes
cannot establish acceptance. Local commit is a handoff, not integration approval.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0; next: production
prerequisites and soak owner handoff.
