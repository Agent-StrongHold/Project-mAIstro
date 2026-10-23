# Issue #860 — bounded repair f129aa83

## Frozen scope

- One item: #860, branch `auto-860`, starting HEAD
  `0ccbc5034a87c2e072f527a9caa4d1577f5c739c`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean starting worktree; no salvage required. No remote mutations or sync requested.
- Inspect existing soak runner/tests/profile, repository instructions, relevant ADRs,
  supplied dispatch evidence and prior failed gate log. Execute the exact vulture
  command before deciding whether a ledger/code repair is warranted.
- Planned write surface: this report; `quality/vulture-baseline.json` only for
  actual reviewed scanner findings. No speculative runtime edits or new tests.
- Ambiguity: dispatch requests CI repair but prior result reports missing RC soak
  acceptance. Treat these as separate obligations; passing static checks cannot
  establish production soak acceptance.
- Current job directory contains no `check-*.log` files at initial inspection.

## Results

Fresh exact Vulture scan passed: 1,323 findings / 1,323 reviewed identities,
zero unclassified or never-allowlist entries (automatic base `4aa68edc0b6b`).
No ledger change is warranted. The supplied historical `check-3.log` reports a
schema-test mismatch (24 actual DDL statements versus 21 expected), not a
Vulture failure. Fresh focused execution does not reproduce it.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,270 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **119 passed, 6 skipped**. Database-gated skips are not integration evidence.
- All validation commands used 1,200-second timeouts.

The captured linked PR bodies and latest issue comments do not supply an exact
promotion RC artifact/configuration or a completed qualifying soak. No remote
list was refreshed. The existing profile explicitly describes a host-process
preflight and lists missing representative workloads. Production-path and ADR inspection completed below; no prior verification claims
adopted.

Additional executed commands (all PASS):

- `uv run python scripts/check-ratchet-provenance.py`: 53 consumers; two non-fatal
  invalid-escape SyntaxWarnings.
- `uv run python scripts/check-shipped-surface-truth.py`.
- `uv run python scripts/check-backlog-consistency.py`: 168 items.
- `git diff --check`.

One inspection path, `packages/maistro-server/src/maistro_server/middleware/rate_limit.py`,
was not found; skipped. The test's actual import resolves to
`packages/maistro-server/src/maistro_server/api/rate_limit.py`, inspected instead.
No validation command failed.

## Architecture and acceptance

Read accepted ADR-081226-69ee, ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`;
physical execution identity is the Attempt ID. The later lease ADR defines
renewal/reclamation beyond the older fencing contract. No authority is changed.
ADR-085's per-principal requirement does not establish distributed budget state;
local 429s cannot waive #860's stronger replica-selection criterion.

| Criterion | Fresh inspection/execution evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` lists missing multi-user/Workspace, Graph fan-out, successful tools/models and Design/Canvas workloads. `scripts/soak/run_soak.py:1373` uses one credential and the mix at 1381 does not cover these surfaces. |
| At least two deployed application replicas | **UNVERIFIED for the RC.** `scripts/soak/run_soak.py:730` explicitly identifies host-uvicorn preflight, not the promoted image/configuration. No fresh deployed soak was run. |
| Sustained saturation, queue growth, lease reclaim/retry, leak observations | **UNVERIFIED.** Focused tests completed in 2.85 seconds; neither these tests nor historical samples prove the required long-window production behavior. |
| No duplicate physical work and Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the schedule probe Run without execution. Admission identity assertions do not prove physical Attempt/effect uniqueness. |
| Rate/security/degraded non-bypass under concurrency | **UNVERIFIED as a whole; independent budgets reproduced.** Both cases of `tests/test_soak_promotion_gates.py:439` passed using production middleware: the same identity receives `[200, 200, 429]` independently from each instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` documents N-times-limit aggregate scope. This is not deployed security soak evidence. |
| Complete production telemetry and explicit thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410` samples driver loop lag, not application loop lag. Driver database probes are not application pool-wait/query latency observations. No fresh complete production series exists. |
| Kill/restart during active physical work; drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427` sends the signal by elapsed time, without requiring an observed active Attempt. Rejoin and aggregate terminal counts do not prove effect uniqueness or absence of silent loss. |
| Long unchanged exact-RC soak | **UNVERIFIED.** `scripts/soak/run_soak.py:730` always returns a failed exact-artifact check for this preflight. Passing fail-closed regression tests are not an actual four-hour RC run. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Gaps recorded locally; no GitHub filing, closure or other mutation permitted or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for an RC soak.** This report identifies the checked source HEAD, not a promoted image/configuration and completed production evidence pack. |

## Handoff

**BLOCKED for #860 acceptance.** The requested CI scan has no unbanked identities;
the historical schema mismatch is already corrected in the starting tree
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:175` includes the
three Gauntlet audit columns). Neither warrants another repair.

Only this report changes. No tests added or removed; inventory delta is zero,
so no inventory note is required. All inherited work and gates remain intact.
Full-tree pytest and a live RC soak were not run. Static checks and isolated
middleware tests are not production acceptance evidence.

Next prerequisite: identify the immutable RC image and normalized runtime config
for promotion; cover the missing supported workloads through existing canonical
execution/authorization seams, observe active physical Attempts and production
telemetry, and run the unchanged long-duration topology. Resolve the budget scope
through the existing rate-limiter seam or accepted contract, not a new authority.
Publish hash-bound evidence and disposition failures before promotion. Repeating
this same clean CI scan or lengthening the host preflight cannot close #860.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. Report commit is a local handoff, not integration approval.
