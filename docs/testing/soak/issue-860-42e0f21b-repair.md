# Issue #860 repair checkpoint — job 42e0f21b

## Frozen scope

- Sole item: issue #860, branch `auto-860`, starting head
  `27f10cedc71356098aeed2ce15880945e0c34750`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree is clean; no uncommitted work to salvage.
- Inspect the supplied dispatch snapshot, previous result and failed check,
  repository guidance, relevant ADRs, existing soak harness and adjacent tests.
- Candidate repair files: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `quality/vulture-baseline.json` (only if the exact scan supplies evidence),
  an inventory note if tests change, and this report. No unrelated inherited
  branch differences will be edited.
- No check-*.log files were present in this job directory at initial inspection.
  Supplied prior check-3.log reports 24 DDL calls versus 21 expected; reproduction
  pending. Prior BLOCKED result is evidence to investigate, not acceptance proof.
- Assumption: this is the explicitly assigned writer/CI-repair round, not the
  verifier-only role. Promotion evidence remains required independently of CI.

## Progress

Fresh reproduction: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passes (37 passed, 6 skipped). The supplied failure is not current.

Exact requested vulture scan passes: 1323 reviewed identities / 1323 findings,
zero unclassified or never-allowlist findings. No ledger or source repair is
justified by these results. Logs: `/tmp/860-42e0-schema.log` and
`/tmp/860-42e0-vulture.log`. Current schema-fence expectations already include
the three Gauntlet audit columns (test lines 173–177).

Additional fresh checks pass: `uv sync --locked --extra dev` (256 resolved,
214 checked); `uv run ruff check .`; `uv run ruff format --check .` (3270 files);
`uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
(66 passed). The latter reproduces independent replica allowances for the same
authenticated/pre-auth identity, not a cluster-wide budget (test line 439).

Read accepted ADR-085, ADR-081626-f383, ADR-082126-f69c and ADR-082526-b36a.
Canonical execution remains `Goal -> Graph -> Run -> NodeRun -> Attempt`;
schedules produce Runs and renewal/reclaim uses the existing fencing contract.
No competing runtime or authorization path is proposed. ADR-085's principal
keying does not make the explicitly process-local middleware cluster-wide;
#860's stronger replica-selection criterion cannot be waived by local tests.

## Acceptance assessment

The ten criteria below are from the supplied issue body, not the previous
worker's assessment. Production installs the inspected limiter at
`packages/maistro-server/src/maistro_server/main.py:648`.

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** Inspected profile and `scripts/soak/run_soak.py:1373`: one credential, health/task/receipt/metrics mix; no representative Workspace population, Graph fan-out, successful model/tool, Canvas or Goal/background traffic. |
| Two deployed application replicas | **UNVERIFIED for RC.** Executed two production-middleware instances in tests, not two deployed immutable artifacts. |
| Sustained saturation, queues, reclaim, backoff and leaks | **UNVERIFIED.** No new sustained deployment run. Sampler tests are not long-window evidence. |
| Physical-work uniqueness and Goal reconciliation | **UNVERIFIED.** Admission identity checks do not prove physical-effect uniqueness or sustained Goal reconciliation. |
| Replica-selection non-bypass for rate/security/degraded behavior | Contrary rate-limit evidence reproduced: same identity gets `[200, 200, 429]` independently on both instances (`tests/test_soak_promotion_gates.py:439`). Full deployed behavior **UNVERIFIED**. |
| Complete telemetry with explicit thresholds | **UNVERIFIED.** Inspected `run_soak.py:1410`: driver loop lag is not application loop latency. No complete fresh production telemetry. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED.** Signal/rejoin code at `run_soak.py:1427` does not by itself establish physical-work recovery; no live recovery run executed. |
| Long exact-RC artifact/configuration soak | **UNVERIFIED.** Executed retained-evidence evaluator: `m3a-round43-shakedown.json` fails `sustain_duration` (420.09 seconds versus 14400 minimum) and `exact_rc_artifact`. Executed assertion that `preflight_artifact_check()['ok'] is False`. No new soak claimed. |
| Findings filed/reclassified before promotion | **UNVERIFIED.** Historical reports are not fresh disposition evidence. No GitHub mutations performed. |
| Machine/human evidence tied to exact promotion hashes | **UNVERIFIED for RC.** Existing preflight artifacts and this validation report do not establish immutable promoted-image/configuration identity. |

The additional `uv run python -` evaluator check passed, confirming retained
short preflight evidence is rejected, not that acceptance is satisfied.
`uv run python scripts/check-doc-links.py` passed (2658 Markdown files, zero
broken links); `git diff --check` passed.

## Disposition and handoff

**BLOCKED** on release acceptance, not the supplied stale schema-test failure or
vulture debt. No new tests, inventory delta, code or ledger changes are warranted
by the reproduced evidence. Only this report changes in this round. Inherited
branch-wide differences are preserved and are not claimed independently verified.

Required next input/work: select the immutable RC image and runtime configuration,
resolve the deployment's replica-budget semantics without a second authorization
path, and execute a representative production-path soak with complete telemetry,
physical-work/recovery accounting and hash-bound evidence. Re-running this same
stale schema failure or a longer host preflight cannot close those gaps. No
merge conflict was present; no develop sync, push, merge or remote mutation.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and production soak acceptance evidence"}`.
Writer validation handoff is complete; issue acceptance remains blocked.
