# Issue #860 repair — job 9a27798f

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`6dc43ee7a68e4953e491a4185fd3ea38480872a3`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
No current-job check logs were supplied. Inspect the explicitly supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log`, reproduce the exact vulture
command, and review retained soak production paths/tests and accepted ADRs.
Candidate edits: this report and, only if the scan warrants it, reviewed
identities in `quality/vulture-baseline.json` or genuinely dead issue-related
source. No unrelated branch-diff repair, new execution authority, GitHub action,
or promotion claim. Existing branch artifacts are preserved.

Ambiguity: the repair request names a CI failure but the last supplied result
was BLOCKED on production evidence. Treat those as separate questions and
validate both; a passing scanner cannot establish release acceptance.

## Results

Fresh checks: `uv sync --locked --extra dev` passed (256 resolved, 214
checked). Exact requested vulture scan passed: 1323 reviewed identities, 1323
findings, zero unclassified/never-allowlist entries. No ledger amendment is
warranted. `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed (37 passed, 6 skipped). The supplied prior check-3.log actually reports
an outdated schema-fence expectation (24 DDL statements versus 21 expected),
not a vulture failure; it does not reproduce on this head.

`uv run ruff check .` passed; `uv run ruff format --check .` passed (3270 files).
`uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
passed (66 tests). These are not production-soak evidence.

`uv run python -` loaded the real driver's evaluator and retained
`docs/testing/soak/evidence/m3a-round43-shakedown.json`: observed sustain
420.09 seconds, required minimum 14400, failed gates `sustain_duration` and
`exact_rc_artifact`. Assertions confirmed both failures and that the current
`preflight_artifact_check()` remains false. No deployment was started or long
soak claimed. `uv run python scripts/check-doc-links.py` passed (2659 Markdown
files, no broken links); `git diff --check` passed.

## Architecture and acceptance review

Read accepted ADR-085, ADR-081626-f383, ADR-082126-f69c and ADR-082526-b36a.
Schedules must produce canonical Runs, and execution/recovery must retain
`Goal -> Graph -> Run -> NodeRun -> Attempt` authority and lease fencing.
An admission counter or process rejoin cannot stand in for physical-work
fencing. ADR-085's principal keying does not establish a cluster-wide store;
the documented process-local #842 contract cannot waive #860's stronger
replica-selection criterion. No competing authorization path is introduced.

The acceptance list comes from the supplied dispatch's issue body. Inspected
production limiter construction (`api/rate_limit.py:95`) and installation
(`packages/maistro-server/src/maistro_server/main.py:648`), the schema-fence
test's current 24-statement contract, the load profile and the driver's
promotion, traffic, sampling and kill/rejoin paths.

| Acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC users/Workspaces, Graph fan-out, schedules, tools/models, Canvas and background profile | **UNVERIFIED.** `scripts/soak/run_soak.py:1373` uses one credential; its mix is health/task/receipt/metrics traffic, not the full requested population. The profile explicitly records missing successful model/tool and Goal/background coverage. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Two production-middleware instances execute in the passing tests, not two immutable deployed RC images. |
| Sustained saturation, queue growth, reclaim/backoff and leaks | **UNVERIFIED.** Sampler/accounting tests pass; no new sustained deployment run. Retained 420.09-second evidence fails the duration gate. |
| Schedule/admission/Goal physical-work uniqueness and fencing | **UNVERIFIED.** Passing receipt-identity probe tests do not prove physical effects or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Contrary allowance evidence reproduced by `tests/test_soak_promotion_gates.py:439`: the same authenticated or pre-auth identity gets `[200, 200, 429]` independently on each middleware instance. Full deployment behavior **UNVERIFIED**. |
| Complete PostgreSQL/application-loop/worker/resource/queue/error telemetry and thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410` measures driver loop lag, not application loop lag; no complete fresh production series. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** The kill/rejoin path at `scripts/soak/run_soak.py:1427` and terminal Run counts do not account for physical effects. No live recovery run executed. |
| Long soak of exact promoted RC artifact/configuration | **UNVERIFIED.** Executed evaluator rejects retained short preflight evidence. `scripts/soak/run_soak.py:730` always rejects host-preflight artifact equivalence, even for a longer run. |
| Findings filed/reclassified before promotion | **UNVERIFIED.** Historical dispositions are not fresh acceptance evidence. No remote mutation performed. |
| Published machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Existing host-preflight evidence and this local validation report cannot establish promoted-image/configuration identity. |

## Disposition

**BLOCKED**, not merge-ready. The supplied schema failure is stale and the
requested vulture scan is clean; changing source, weakening a test or adding
ledger identities would be unsupported. Only this report changes in this round;
no test addition or inventory delta is needed. All inherited work is preserved.
No merge conflict was present, so no develop sync was attempted.

Next work requires a selected immutable RC image/configuration and a
production-path representative soak runner, complete telemetry and physical-work
accounting, plus resolution of replica-budget semantics through the existing
security authority. Repeating this stale CI repair or extending the host
preflight duration cannot establish those prerequisites. Inherited branch-wide
differences are not independently approved by this focused validation.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC deployment and production soak acceptance evidence"}`.
Writer validation is complete for handoff only; issue acceptance remains blocked.
