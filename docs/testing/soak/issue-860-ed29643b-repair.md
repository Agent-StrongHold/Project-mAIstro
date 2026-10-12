# Issue #860 — repair ed29643b

## Frozen scope

One issue: #860, branch `auto-860`, starting HEAD
`cb1e32cbb5c60070a69a5a46a6fc66c46860a573`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Starting worktree is clean.
No salvage or develop-conflict resolution is needed. No remote mutation.

Inspect the supplied dispatch snapshot, repository instructions, relevant ADRs,
existing soak runner/profile/tests, production seams they exercise, historical
failed check and prior result. Write scope is this report, plus only repairs
justified by fresh failures in those inspected files; reviewed Vulture identities
may be amended in `quality/vulture-baseline.json` under the explicit CI exception.
Do not enumerate new issues/PRs or trust historical verification claims.

Initial evidence: this job directory has no `check-*.log` files. The supplied
historical `98a11313.../check-3.log` fails the learning-schema fence test (24 DDL
statements versus 21 expected). Prior result reports BLOCKED, not a sync conflict.
Ambiguity: CI repair and production soak acceptance are separate obligations;
validate both honestly without inventing an immutable RC or deployment target.

## Fresh results

- Exact requested Vulture scan: PASS, 1,323 findings / 1,323 reviewed
  identities; zero unclassified and never-allowlist findings. Automatic gate
  comparison base is `4aa68edc0b6b`. No ledger amendment is warranted.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,270 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **119 passed, 6 skipped in 2.64s**. The historical schema failure does not
  reproduce. Skips are not database integration evidence.

All validation above used a 1,200-second timeout. No production change is
justified by these results. Additional gates passed with 1,200-second timeout:
`uv run python scripts/check-ratchet-provenance.py` (53 consumers; two non-fatal
invalid-escape SyntaxWarnings), `uv run python scripts/check-shipped-surface-truth.py`,
`uv run python scripts/check-backlog-consistency.py` (168 items), and
`git diff --check`.

## Architecture and acceptance

Read accepted ADR-081226-69ee, ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`;
physical runtime identity is the Attempt ID. The later lease ADR adds renewal and
reclaim to the earlier fencing contract. ADR-085 requires principal-keyed rate
limits but does not establish distributed state. Local rejection cannot waive
#860's stronger replica-selection acceptance. No authority or gate is changed.

| Acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` lists missing users/Workspaces, Graph fan-out, successful tool/model calls and Design/Canvas. `scripts/soak/run_soak.py:1373` uses one credential and its request mix at 1381 lacks these workloads. |
| Two deployed application replicas | **UNVERIFIED for RC.** `scripts/soak/run_soak.py:730` explicitly marks host uvicorn as preflight, not the production artifact. ASGI middleware instances in passing tests are not deployed replicas. |
| Sustained saturation, queues, reclaim/retry, leaks | **UNVERIFIED.** No fresh long-window production run executed; focused tests took 2.64 seconds. Historical samples do not establish current RC behavior. |
| Exactly-once/fenced physical work and Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without execution. Admission identity tests do not establish physical Attempt/effect uniqueness. |
| Rate/security/degraded non-bypass | **UNVERIFIED as a whole; independent allowances reproduced.** Both cases of `tests/test_soak_promotion_gates.py:439` passed through production middleware: the same identity gets `[200, 200, 429]` independently on each instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` documents N-times-limit aggregate scope. |
| Complete telemetry with thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410` measures driver event-loop lag, not application lag. No fresh complete production telemetry series or saturation proof. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427` signals by elapsed time, without requiring an observed active Attempt. Rejoin and terminal Run totals alone cannot prove absence of duplicate effects or silent loss. |
| Long unchanged exact-RC soak | **UNVERIFIED.** `scripts/soak/run_soak.py:730` always fails exact-artifact evidence. The executed four-hour-preflight CLI regression tests prove fail-closed behavior, not a four-hour soak. |
| Findings disposition before promotion | Local gaps recorded here; external filing/reclassification **UNVERIFIED**. No GitHub mutations performed or permitted. |
| Machine/human evidence tied to artifact/config hashes | **UNVERIFIED for RC.** This report identifies checked source, not a promoted image/config and completed production evidence pack. |

## Handoff

**BLOCKED for #860 acceptance.** No fresh scanner failure warrants ledger changes.
The historical schema mismatch is already fixed in the starting tree:
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175` includes the
three Gauntlet audit columns and independently asserts all 24 ordered statements.
Do not add speculative code or duplicate that repair.

Only this report changes. No tests added/removed; inventory delta is zero, so no
inventory note is required. Inherited work is preserved. Full-tree pytest, live
PostgreSQL integration and a production RC soak were not run.

Next prerequisite: select the immutable promotion RC and normalized production
configuration; complete representative workloads through canonical execution and
authorization seams, observe physical Attempts and application telemetry, resolve
replica-budget scope, and execute the unchanged long-duration deployment. Publish
hash-bound evidence and disposition failures. Another clean static scan or a
longer host preflight cannot satisfy these prerequisites.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; validation
errors 0. This local report commit is a handoff, not integration approval.
