# Issue #860 — bounded repair af3b8055

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `aa4ef413ef988fd53f314eee81632cac571533ae`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean; no incoming edits to salvage.
- Repair candidates: `quality/vulture-baseline.json` only if the required scan
  identifies reviewed retained debt; issue soak harness/tests only if fresh
  evidence identifies a focused defect; this report. No unrelated inherited
  differences will be modified.
- Read-only evidence: supplied dispatch snapshot, prior result/check log,
  repository instructions, relevant ADRs, soak profile/harness/tests and
  production rate-limiter wiring.
- No `check-*.log` files were present in the supplied job directory at initial
  inspection. The named previous check log will be inspected instead.
- Ambiguity: the assignment requests CI repair but the previous result reports
  missing RC acceptance evidence. Run the exact requested gate before deciding
  whether a ledger change is justified. No GitHub mutation or new authority.

## Results

- Required vulture command passed: 1,323 findings / reviewed identities, zero
  unclassified or never-allowlist findings. It selected base `4aa68edc0b6b`.
  No ledger amendment is justified by this fresh scan.
- Historical `check-3.log` fails the learnings schema-fence assertion (24 DDL
  statements observed, 21 expected), not vulture. Fresh execution of
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. Historical failure does not reproduce.
- Fresh execution of `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: 82 passed. These are focused regressions, not deployed RC soak proof.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,270 files).
- `uv run python scripts/check-ratchet-provenance.py`: PASS (53 consumers;
  non-fatal invalid-escape SyntaxWarnings emitted by AST scans).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Commands used 1,200-second timeouts. No source/test change justified; no new
  tests or inventory-count delta, so no inventory note required.

## Architecture and acceptance review

Read accepted ADR-081426-1f7c (physical execution identity is Attempt),
ADR-081626-f383 (canonical durable execution fence), ADR-082126-f69c (recurrence
produces Runs, no second runtime), and ADR-085 (per-principal rate limits).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission deduplication
cannot stand in for physical execution uniqueness. ADR-085 does not establish
that process-local rate enforcement meets the issue's stronger replica-selection
criterion. No new scheduler, authorization path or execution authority is added.

The historical schema-fence failure is already addressed in the current test:
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-179` independently
lists the three validation-audit columns absent from the old 21-statement
expectation. The fresh suite passes without relaxing assertions. Six skipped
integration cases are not live database proof.

| Acceptance criterion | Reachable evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `scripts/soak/run_soak.py:1373-1395` uses one credential and health/task/receipt/metrics traffic. `docs/testing/soak/m3a-load-profile.md:152` acknowledges missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workloads. No selected immutable promotion artifact/configuration was supplied. |
| At least two application replicas | **UNVERIFIED for RC.** `run_soak.py:730-742` explicitly identifies host-uvicorn preflight, not promoted Compose. Executed ASGI tests do not deploy two RC replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff, leaks and restart | **UNVERIFIED.** No sustained production load or long-window telemetry executed this round. Unit regressions cannot establish this criterion. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044-1077` cancels the schedule probe Run without execution; the probe proves admission only. No physical-effect or Goal reconciliation observation. |
| Rate/security/degraded concurrency non-bypass | **UNVERIFIED overall; independent allowances reproduced.** Both parametrizations of `tests/test_soak_promotion_gates.py:439` passed against production middleware: the same identity receives `[200, 200, 429]` separately on both instances. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37,96` documents and constructs process-local limits. This does not prove a replica-independent budget. |
| Complete telemetry with explicit pass/fail thresholds | **UNVERIFIED.** `run_soak.py:1410-1423` samples driver loop lag, not application loop lag. No fresh complete PostgreSQL/worker/queue/resource/error series. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1427-1450` signals based on elapsed time, not an observed active Attempt. Rejoin/terminal Run counts alone cannot prove physical recovery. |
| Long unchanged exact-RC soak | **UNVERIFIED.** `run_soak.py:1551` always emits a failing exact-artifact check. Executed `test_four_hour_preflight_cannot_pass_cli` rejects missing/null/preflight evidence even with synthetic four-hour duration; no actual four-hour RC run performed. |
| Findings filed/reclassified before promotion | Local disposition recorded in this report. External filing/reclassification **UNVERIFIED**, and remote mutations prohibited. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for RC.** This report identifies source HEAD but is not a deployed-artifact evidence pack. No image/config-bound production results produced. |

## Disposition and handoff

**BLOCKED**, not merge-ready. The requested CI scan and historical test failure
are clear on fresh execution; speculative ledger/source changes would not repair
the missing acceptance evidence. Only this report changes in this round.

Next prerequisite: designate immutable promotion image/configuration and a
representative workload; disposition the replica-selection allowance gap at its
owning invariant; observe canonical physical Attempts and active-work recovery;
then execute an unchanged long RC soak and publish hash-bound evidence. Another
identical static CI-repair round cannot supply those prerequisites. No full-tree
pytest, deployed RC soak, or live database integration is claimed.

Progress: checked 1 issue; CI investigation done 1; acceptance-complete 0;
skipped issues 0; fresh command errors 0. Commit this report locally. No push,
PR, issue closure, gate relaxation, ledger/grant edit, or unrelated repair.
