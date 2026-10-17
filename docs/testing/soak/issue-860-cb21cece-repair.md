# Issue #860 — bounded repair cb21cece

## Frozen scope

- Assigned issue only: #860; no PR or GitHub mutations.
- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD `c514fb1364d16f450c646004095d12d824f9fefa`;
  dispatched base `2154f845347c9541016288c760f8da3f5cd2e064`.
- Evidence snapshot: dispatch-context.json and supplied prior result/check log.
- Files to inspect: repository instructions, applicable ADRs, soak runner/profile,
  adjacent soak tests, vulture checker/ledger and CI arguments.
- Candidate edits limited to evidenced vulture identities, associated tests and
  inventory notes if needed, and this handoff. No new runtime authority.

## Initial results

Current job directory has no check-*.log files. Prior result reports BLOCKED;
that is a claim to verify, not promotion evidence. No uncommitted work to salvage.
Assumption: the explicit CI-repair request authorizes only reviewed ledger repairs;
it does not authorize fabricating an RC identity or treating host preflight as soak.

## Reproduced checks

- Exact requested vulture command: PASS, 1323 findings / reviewed identities,
  zero unclassified and never-allowlisted. No ledger amendment is warranted.
  Log: `/tmp/860-cb21-vulture.log`.
- Supplied prior `98a11313167b41a98a420abfda80c292/check-3.log` reports the
  schema-fence assertion expected 21 statements but observed 24. Current test
  independently lists all three Gauntlet audit columns; no weakening needed.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  PASS, 117 passed, 6 skipped (live PostgreSQL coverage not established).
  Log: `/tmp/860-cb21-tests.log`.
- Guessed README glob under scripts/soak and docs/testing/soak was not found;
  skipped, using the actual `m3a-load-profile.md` instead.

## Architecture reconciliation

Read accepted ADR-081226-a66b (Run/NodeRun/Attempt ownership), ADR-081626-f383
(canonical store fencing, explicitly not implicit expiry takeover), ADR-085
(per-principal limits), and proposed ADR-081 (deployment). Do not turn admission
uniqueness into physical-work evidence or a proposed deployment ADR into a waiver.
The profile acknowledges missing workload classes and per-process rate semantics;
these do not satisfy issue acceptance. No new runtime authority is introduced.

## Additional executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- `git diff --check`: PASS.
- `uv run pytest packages/maistro-server/tests -x -q`: PASS, 558 passed,
  8 skipped, 22 deprecation warnings (31.49 s). Log: `/tmp/860-cb21-server.log`.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-server/tests`: PASS, 566 collected/expected, no duplicates.
- Executed current runner via `uv run python` / `runpy.run_path` and asserted
  that `preflight_artifact_check()['ok'] is False`; evaluated historical
  `docs/testing/soak/evidence/m3a-round6-shakedown.json`: failed gates are
  exactly `sustain_duration` and `exact_rc_artifact`. This is gate validation,
  not new load evidence.

## Acceptance review

| # | Criterion | Executed evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC profile | Profile defines traffic but explicitly omits users/Workspaces, fan-out, successful tools/models, Canvas and Goal work (`m3a-load-profile.md`, Remaining representative-profile gaps). Complete selected-RC profile UNVERIFIED. |
| 2 | Two production application replicas | Boot-contract tests pass; no deployed RC replicas exercised in this round. UNVERIFIED. |
| 3 | Sustained saturation, reclaim, retry, leaks | Current evaluator rejects historical duration. No new long-window workload. UNVERIFIED. |
| 4 | No duplicate physical work, admission and Goal reconciliation | Server/admission tests pass, but `run_soak.py:1067` explicitly cancels the admission probe without execution. Physical effects and sustained reconciliation UNVERIFIED. |
| 5 | Rate/security/degraded behavior not bypassable by replica choice | Counterexample freshly reproduced: `test_soak_promotion_gates.py:439-488` obtains `[200,200,429]` independently on each real middleware instance for both identity classes. `api/rate_limit.py:32-37` declares process-local state. Shared allowance criterion NOT MET; full production security/degraded behavior UNVERIFIED. |
| 6 | All telemetry and explicit thresholds | Sampler/threshold tests pass, but driver-loop lag is not application-loop latency and no complete current RC telemetry was produced. UNVERIFIED. |
| 7 | Kill/restart during active work with drain/fencing/recovery | No current RC active-work restart executed. Process exit/rejoin does not establish physical-effect safety. UNVERIFIED. |
| 8 | Long-running exact RC artifact/config soak | Current `run_soak.py:744-755` rejects host preflight regardless of duration; CLI rejection test passes. No frozen RC manifest or >=4-hour run supplied/executed. UNVERIFIED. |
| 9 | Findings classified to earliest broken invariant | Backlog consistency passes, not proof of complete classification. UNVERIFIED; GitHub mutations prohibited. |
| 10 | Human/machine evidence bound to exact hashes | Historical evidence fails current promotion checks; this report records validation only. No new hash-bound RC soak. UNVERIFIED. |

## Final disposition and next action

**BLOCKED** for issue #860 acceptance. Both the specifically reported historical
schema-test failure and suspected vulture debt are absent on the assigned head.
Changing tests or ledger rows merely to create a repair would be unsupported.
Only this handoff changed; no runtime, tests, inventory counts or quality ledgers
changed. Existing meaningful tests were executed rather than duplicated, so no
inventory delta note is required.

Next: select/freeze the exact RC image/config manifest, complete representative
production workloads and physical-effect/recovery probes, reconcile the shared
rate-limit requirement with the documented local policy, and execute the fresh
>=4-hour instrumented soak. These are unresolved acceptance prerequisites, not
an assertion that Docker cannot run. No deployment was attempted in this bounded
CI-repair round and no historical deployment claims were accepted as current
production evidence. Do not schedule another identical ledger repair expecting
it to satisfy these operational and contract gaps.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
validation failures 0; blocked 1. Local commit is a handoff, not integration or
promotion approval. No push, PR, comment or issue closure performed.
