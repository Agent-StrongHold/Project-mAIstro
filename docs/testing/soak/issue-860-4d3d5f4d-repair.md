# Issue #860 — repair checkpoint (4d3d5f4d)

## Frozen scope

- Sole item: issue #860, assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `1cdf2064f54df1dbc42ffbd255c4f9ac381d6f2f` (resolved, clean).
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved).
- Evidence: supplied dispatch-context.json, prior result ed29643b, cited
  check-3.log in job 98a11313, existing soak runner/profile/tests and relevant ADRs.
- Candidate edits: this report; `quality/vulture-baseline.json` only if a fresh
  exact scanner failure requires reviewed identity reconciliation. No guessed
  production changes, no policy/grant changes, no GitHub mutations.

## Initial observations

The current job directory contains no `check-*.log` files. The prior result is
BLOCKED, not proof of current behavior. The inherited branch has extensive
changes relative to the supplied base; these are preserved, not discarded.
Assumption: the explicit writer/CI-repair assignment takes precedence over the
prompt's verifier-only no-edit clause. This round validates locally and records
unproven promotion criteria honestly.

## Fresh validation checkpoint

- Exact requested Vulture command: PASS, 1,323 reviewed identities / 1,323
  findings; zero unclassified or never-allowlist findings. The gate selected
  comparison base `4aa68edc0b6b`. No ledger edit is justified.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,270 files).
- Historical check-3.log was read: schema-fence test expected 21 statements but
  observed 24. Fresh targeted reproduction passes: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
  tests/test_gitleaksignore_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  reports **119 passed, 6 skipped in 2.79s**. Database skips are not integration
  evidence. No speculative schema repair is warranted.

Additional gates (all PASS):

- `uv run python scripts/check-ratchet-provenance.py`: 53 consumers; two
  non-fatal invalid-escape SyntaxWarnings.
- `uv run python scripts/check-shipped-surface-truth.py`: matrix complete.
- `uv run python scripts/check-backlog-consistency.py`: 168 items.
- `git diff --check`: no whitespace errors.

Commands used a 1,200-second timeout.

## Architecture and acceptance review

Read accepted ADR-081226-69ee, ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`; physical runtime identity is the Attempt ID. The later lease ADR
extends fencing with renewal/reclaim. ADR-085's principal-keyed rate limits do
not establish distributed enforcement. Local enforcement is not a waiver of
#860's replica-selection requirement. No authority, scheduler or gate changed.

| #860 acceptance | Fresh evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` identifies missing users/Workspaces, Graph fan-out, successful tool/model calls and Design/Canvas. Inspected `scripts/soak/run_soak.py:1373` uses one credential; its mix at 1381 omits these workloads. |
| At least two deployed application replicas | **UNVERIFIED for the RC.** `scripts/soak/run_soak.py:730` explicitly identifies host uvicorn preflight, not the promoted image/configuration. Two ASGI instances in unit tests are not two deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retries and leaks | **UNVERIFIED.** No fresh long-duration RC workload executed. The 2.79-second tests cannot establish these observations. |
| Exactly-once/fenced physical work, admission and Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without execution. Passing receipt-identity tests establish evaluator behavior, not physical Attempt/effect uniqueness. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; independent budgets reproduced.** Both parameterizations at `tests/test_soak_promotion_gates.py:439` passed against production middleware: the same identity gets `[200, 200, 429]` separately on each instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` explicitly documents N-times-limit aggregate scope. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410` samples driver loop lag, not application loop lag. No fresh production PostgreSQL/worker/queue/error telemetry series captured. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427` schedules the signal by time without requiring an observed active Attempt. Rejoin/terminal Run totals do not prove physical recovery. |
| Long soak of unchanged exact RC | **UNVERIFIED.** `scripts/soak/run_soak.py:730` always fails exact-artifact evidence. Executed four-hour-preflight CLI tests at `tests/test_soak_promotion_gates.py:105` prove fail-closed handling of synthetic evidence, not four hours of load. |
| Disposition of load findings before promotion | Gaps recorded locally in this report; external filing/reclassification **UNVERIFIED**. No GitHub mutations permitted or performed. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC.** This report identifies checked source only; it is not a production evidence pack. |

The schema-fence test already lists the three Gauntlet audit upgrades at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175` and checks all
24 statements independently of production constants. Preserve that existing fix.

## Handoff

**BLOCKED for #860 acceptance.** The cited CI failure does not reproduce, and
the exact scanner passes, so no ledger amendment or production repair is
justified. Only this report changes. No tests added/removed; inventory delta is
zero and no inventory note is required. Inherited work is preserved.

Next prerequisite: select an immutable promotion RC and normalized production
configuration, complete the representative workload through canonical execution
and authorization seams, observe physical Attempts and application telemetry,
resolve the replica-budget acceptance gap, and run the unchanged long-duration
deployment. Bind machine/human evidence to its hashes and disposition findings.
A longer host preflight or another static scan cannot meet these requirements.
Full-tree pytest, live PostgreSQL integration and a production RC soak were not
run. No branch synchronization conflict was present; no fetch/merge was needed.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; validation
errors 0. The local report commit is a handoff, not integration approval.
