# Issue #860 repair checkpoint

Frozen scope: issue #860, branch auto-860, starting HEAD
f69ba79edf22ce56e5d01ed69fac0f84155089d4, base
2154f845347c9541016288c760f8da3f5cd2e064. No other issues or PRs will
be processed. Starting worktree is clean; no salvage patch needed.

Assigned evidence: job 7fd0305e83144cd6b143937c0ede8bc5 dispatch context,
prior result 73d2846f142443a4ae9efc9253736b88, and prior check-3.log from
98a11313167b41a98a420abfda80c292. Current job has no check-*.log files.

Repair candidates frozen before edits: packages/maistro-core/tests/persistence/test_pg_learnings.py,
quality/vulture-baseline.json (only if exact scan requires reviewed reconciliation),
this report and docs/testing/inventory-notes/issue-860-schema-repair.md.
Read-only architecture/acceptance inspection covers the existing #860 soak harness,
its tests and report, pg_learnings implementation, repository instructions and relevant ADRs.

Ambiguity: dispatch requests repair but previous result is BLOCKED on deployed
promotion evidence. Proceed with reproduction of the concrete schema-test failure
and exact vulture gate; do not invent deployed RC evidence or change execution authority.
Prior check-3.log reports 24 fenced DDL calls versus 21 expected by the test.
Prior BLOCKED verdict is not accepted as fresh validation.

Fresh reproduction: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed (37 passed, 6 PostgreSQL-dependent skips). The three audit columns are
already present in the independent expected DDL list at lines 175–177. The
reported historical test failure is no longer reproducible; no speculative test
repair is warranted.

Exact requested vulture command passed: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
1323 reviewed identities match 1323 findings, zero unclassified or never-allowlist.
No ledger amendment is warranted. No tests added; inventory delta is zero.

Additional fresh checks: `uv run ruff check .` passed;
`uv run ruff format --check .` passed (3277 files);
`uv run pytest tests/test_soak_promotion_gates.py -x -q` passed (72 tests);
`uv run python scripts/check-backlog-consistency.py` passed (168 items).
The passing gate tests include rejection of a four-hour host preflight as RC
proof and reproduction of independent production limiter allowances on replicas.
These are negative acceptance evidence, not promotion success.

## Architecture reconciliation

Read repository AGENTS.md and docs/README.md, ADR-081 (Proposed, not an
accepted topology waiver), accepted ADR-085 (per-principal rate enforcement),
and accepted ADR-081226-a66b (Run -> NodeRun -> Attempt lifecycle).
Admission uniqueness does not prove physical Attempt uniqueness. Retain
Goal -> Graph -> Run -> NodeRun -> Attempt; no new execution, event, Goal,
or authorization authority is introduced. Existing process-local rate semantics
cannot waive the issue's replica-selection requirement. BACKLOG.md:267–276
already records that gap as engine-116; no GitHub mutation was made.

## Acceptance audit

| #860 criterion | Fresh evidence / disposition |
|---|---|
| Representative RC load profile | UNVERIFIED: inspected m3a-load-profile.md; it explicitly omits concurrent users/Workspaces, fan-out, successful tools/models and Design/Canvas. |
| Two deployed application replicas | UNVERIFIED: no exact-RC deployment was executed in this repair. ASGI instances are not deployed replicas. |
| Sustained saturation, queue/reclaim/retries, memory/descriptor/process leaks | UNVERIFIED: no sustained production run was executed. Unit passes and six skipped database tests cannot establish this. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | UNVERIFIED: run_soak.py:1067 onward cancels the queued schedule-probe Run; admission counts are not physical-work evidence. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Negative evidence: test_soak_promotion_gates.py:439–487 passed for both identity classes, showing [200,200,429] on each separate production middleware instance for the same identity. Deployed security/degraded behavior remains UNVERIFIED. |
| Full telemetry and explicit thresholds | UNVERIFIED: inspected profile distinguishes driver loop lag from application loop lag and documents missing production worker/pool/lease observations. No new telemetry collected. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED: no live active-work kill/restart performed; exit/rejoin alone would not prove Attempt recovery. |
| Long soak of exact RC/config | UNVERIFIED: run_soak.py:744–755 returns exact_rc_artifact.ok=false. Executed tests reject four-hour preflight evidence. No designated immutable RC image/config was executed. |
| Classify load findings to earliest invariant | Partial: existing engine-116 records replica-selection gap; backlog consistency passes. Completeness for a new RC soak is UNVERIFIED. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for the RC: historical preflight packs are not a new run at this HEAD. This handoff is validation metadata only. |

## Final disposition and handoff

BLOCKED, not integration approval. The concrete historical CI failure is already
repaired and the exact identity ledger passes; there is no evidence-backed code
or ledger repair to make in this round. Only this checkpoint file changed.
No tests were added or modified, so no inventory-note addition is required.
No full-tree pytest, live PostgreSQL, or production soak was run.

Next: designate the immutable promotion image/configuration and representative
production workload; resolve the already-recorded cluster rate-limit gap through
the canonical enforcement path; then collect an exact-artifact >=4-hour soak
with active Attempt recovery/uniqueness and full telemetry. Re-running this
host preflight or amending an already-matching vulture ledger cannot unblock it.

Progress: checked 1 assigned issue; completed local validation/handoff 1;
acceptance completion 0; skipped issues 0; command failures 0. Residual risk is
unproven release behavior, not a scanner finding. Preserve all prior branch work.
