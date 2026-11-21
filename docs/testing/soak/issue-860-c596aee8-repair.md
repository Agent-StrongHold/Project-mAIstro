# Issue #860 — bounded repair c596aee8

## Frozen scope

One issue: #860, branch `auto-860`, starting HEAD
`bbbb547e58b6c12c44e24238182c955a98389b86`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Working tree was clean.
No PRs or other issues will be processed; supplied dispatch is evidence only.

Files eligible for repair: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`quality/vulture-baseline.json` (explicit CI-repair exception), this report,
and an inventory note if tests change. Adjacent architecture/tests are read-only.

The supplied historical check-3.log reports 24 schema statements against 21
expected. The previous result reports missing exact-RC soak evidence. Neither
claim is accepted without revalidation. No check-*.log files were present in
this job directory at entry. Assumption: writer role; run focused checks and
commit findings even if release acceptance remains blocked. No deployment RC
identity/configuration is supplied; a host preflight cannot substitute for it.

## Results

Fresh required vulture scan passes: 1,323 reviewed identities / 1,323 findings,
zero unclassified and forbidden findings (scanner-selected base `4aa68edc0b6b`).
No ledger amendment is warranted. Fresh `uv run pytest
packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passes:
37 passed, 6 skipped in 1.60s. The inherited test already includes the three
Gauntlet audit columns; the supplied historical schema failure does not reproduce.
The skipped database tests are not live integration evidence.

A documentation search used nonexistent README globs (rg exit 2); no content
was inferred from those missing files. The actual profile and ADRs were read.

Additional fresh commands (1,200-second timeout), all passing:

- `uv run ruff check .`
- `uv run ruff format --check .` — 3,270 files formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — 82 passed in 2.59s. Combined with the schema suite: 119 passed, 6 skipped.
- `uv run python scripts/check-ratchet-provenance.py` — 53 consumers;
  two non-fatal invalid-escape SyntaxWarnings.
- `uv run python scripts/check-shipped-surface-truth.py` — matrix complete.
- `uv run python scripts/check-backlog-consistency.py` — 168 items.

## Architecture reconciliation

Read accepted ADR-081226-69ee, ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`; the physical execution identity is the Attempt ID, not a Run receipt.
The later lease ADR adds renewal/reclaim to the original fencing contract.
ADR-085 requires principal-keyed limits but does not prove distributed budgets.
The documented process-local implementation is not a waiver of #860's
replica-selection acceptance. No execution or authorization authority changed.

## Acceptance review against current code and executed tests

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` records missing workloads. `scripts/soak/run_soak.py:1373` uses one credential; the mix at 1381 omits concurrent Workspaces, Graph fan-out, successful tool/model and Design/Canvas operations. |
| Two deployed application replicas | **UNVERIFIED for RC.** `scripts/soak/run_soak.py:730` declares host-process preflight, not the promoted deployment. ASGI test instances do not prove a deployed topology. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff and leaks | **UNVERIFIED.** No long-duration RC load was executed; these short tests establish no sustained observations. |
| Physical-work uniqueness, admission and Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels the admitted schedule Run without execution. Receipt uniqueness is not physical Attempt/effect uniqueness. |
| Rate/security/degraded non-bypass across replicas | **UNVERIFIED overall; independent allowances reproduced.** Both cases of `tests/test_soak_promotion_gates.py:439` pass against production middleware: identical identities obtain `[200, 200, 429]` separately on each replica. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` documents this N-times-limit scope. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410` samples driver loop lag, not application event-loop lag. No fresh PostgreSQL/worker/queue/error production telemetry series exists from this round. |
| Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427` signals by elapsed time without requiring an observed active Attempt. Process rejoin and terminal Run totals cannot prove physical recovery. |
| Long unchanged exact-RC soak | **UNVERIFIED.** `scripts/soak/run_soak.py:730` always rejects exact-artifact equivalence; passing synthetic duration tests cannot establish a four-hour deployment run. |
| Findings disposition before promotion | Recorded locally here; external filing/reclassification **UNVERIFIED**. GitHub mutations are prohibited and none were performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for RC.** This report binds local checks to source HEAD only, not to a promoted image/configuration. |

## Handoff

**BLOCKED for issue acceptance.** The explicit CI-repair check passes without
ledger changes; the historical schema mismatch is already repaired in inherited
work. No production/test change is warranted by these checks. Only this report
changes; no test additions/removals, so no inventory delta or note is required.
No full-tree pytest, live database integration or RC soak was run. No synchronization
conflict exists and no fetch/merge was needed. Existing work was preserved.

Next prerequisite: supply the immutable promotion RC and normalized production
configuration, complete representative canonical-path workloads and physical
Attempt telemetry, resolve the replica-budget acceptance gap, then run and
hash-bind a new unchanged long-duration deployment soak. Do not retry this same
static repair expecting it to establish production acceptance.

Progress: checked 1, acceptance-complete 0, skipped 0 issues, validation errors 0
(one missing-file documentation search noted above). The local report commit is
handoff only, not integration approval.
