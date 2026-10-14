# Issue #860 repair checkpoint

## Follow-up job ac09fde9cd724bf8a8e7799e4fbee0b1

Frozen scope: issue #860 only; assigned worktree auto-860, starting HEAD
65dd9d50714e3c76cdabb6f956f419a6b8ebe540 verified, worktree initially clean.
Supplied base: 2154f845347c9541016288c760f8da3f5cd2e064. No remote mutations.
Edit scope: this checkpoint; the vulture ledger and historical schema-test
expectations only if fresh failures justify repair. No such failures reproduced.
Current job directory has no check-*.log files. Read the supplied historical
98a11313167b41a98a420abfda80c292/check-3.log and prior result; neither is a
current validation claim. Ambiguity resolved conservatively: this is a writer
repair round, not permission to replace missing production evidence with tests.

Fresh execution:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1323 reviewed identities / 1323 findings, zero unclassified and
  never-allowlist findings. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`
  passed: 109 passed, 6 skipped. The historical 24-versus-21 schema failure
  no longer reproduces: test_pg_learnings.py:175–177 already lists the three
  audit columns inside the independently asserted advisory-lock fence.

Production reachability and architecture were checked, not inferred from passes:
`main.py:648` installs `RateLimitMiddleware`, whose constructor at
`api/rate_limit.py:90–98` creates an instance-local InMemoryRateLimiter.
The executed regression `test_soak_promotion_gates.py:439–487` obtains
[200, 200, 429] independently on both instances for the same authenticated or
unauthenticated identity. This falsifies a shared allowance, not deployed
security correctness. BACKLOG.md:267–279 already classifies this as engine-116,
with a cluster-budget specification decision pending.

Read AGENTS.md, docs/README.md, accepted ADR-085, ADR-081226-a66b and
ADR-081626-f383, and proposed ADR-081. Preserve Goal -> Graph -> Run ->
NodeRun -> Attempt; do not create a second execution or authorization authority.
ADR-081626-f383 requires physical execution fencing, so admission counts and
process rejoin cannot stand in for that proof. The proposed topology ADR does
not waive issue acceptance. run_soak.py:1067–1092 explicitly cancels its queued
schedule probe without execution; run_soak.py:744–755 always rejects its host
preflight as an exact-RC artifact. The inspected load profile explicitly records
missing representative traffic and telemetry. No new production soak was run.

### Acceptance disposition for this job

| Criterion | Fresh evidence / disposition |
|---|---|
| Representative RC workload | UNVERIFIED: m3a-load-profile.md explicitly lacks multi-user/Workspace, fan-out, successful tools/models, Design/Canvas and background/Goal traffic. |
| Two production replicas | UNVERIFIED: executed ASGI tests are not a deployed RC. |
| Sustained saturation/reclaim/retries/leaks | UNVERIFIED: no sustained deployed workload; six DB tests skipped. |
| Physical-work uniqueness and Goal reconciliation | UNVERIFIED: schedule admission probe does not execute physical work. |
| Replica-selection non-bypass | Negative evidence: executed production middleware regression demonstrates independent allowances; deployed security/degraded behavior UNVERIFIED. |
| Full telemetry and explicit thresholds | UNVERIFIED: profile records incomplete worker/pool/lease and application-loop observations. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: no active Attempt restart experiment performed. |
| Long exact-RC soak | UNVERIFIED: executed tests reject even four-hour host preflight; no immutable promotion image/configuration exercised. |
| Findings classified before promotion | Partial: existing engine-116 classifies allowance gap; completeness for a new RC soak UNVERIFIED. |
| Hash-bound machine/human production evidence | UNVERIFIED: this checkpoint is local validation metadata only. |

No code, tests, runtime configuration, inventory notes or ledger changed.
Inventory delta: zero. Additional fresh validation passed:
`uv run ruff check .`, `uv run ruff format --check .` (3277 files),
`uv run python scripts/check-backlog-consistency.py` (168 items), and
`git diff --check`.

Disposition: BLOCKED. Historical CI failure is already repaired; exact-debt
ledger matches the real scan. Do not dispatch another identical scanner-only
repair expecting it to establish production acceptance. Next requires a designated
immutable RC/configuration, the canonical cluster-budget specification decision,
a representative production workload and >=4-hour deployment evidence including
active Attempt recovery and full telemetry. No full-tree pytest or live
PostgreSQL/production soak was run in this job. Only this checkpoint is committed
locally; no integration approval or GitHub mutation.
Progress: checked 1, local validation/handoff done 1, acceptance complete 0,
skipped issues 0, command errors 0; next: production acceptance work above.


## Follow-up job 0bf3afc0270f4fa1aa137b502934efdb

Frozen scope: only issue #860 in auto-860, clean starting HEAD
9d010eb5eb011f0dd5cc2c2f64f2bb3b4eab313a, supplied base
2154f845347c9541016288c760f8da3f5cd2e064. No PR processing or remote mutations.
Files eligible for edits: this checkpoint, quality/vulture-baseline.json only
for actual reviewed scan differences, and
packages/maistro-core/tests/persistence/test_pg_learnings.py plus
its existing inventory note only if the historical failure reproduces.
Read-only scope: repository instructions, relevant lifecycle/rate-limit ADRs,
existing soak profile/harness/tests, and supplied job artifacts.

Fresh initial evidence: current job contains no check-*.log files. The supplied
historical check-3.log fails because 24 fenced DDL statements were observed
against 21 expected. The prior result is BLOCKED, not evidence of current passes.
Assumption: repair actual reproduced CI failures; do not invent exact-RC load
results or broaden this lane into the separate rate-limit implementation issue.
Fresh validation: exact requested vulture scan passed (1323 reviewed identities,
1323 findings, zero unclassified/never-allowlist). Combined focused pytest
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`
passed: 109 passed, 6 skipped. The historical 24-versus-21 failure does not
reproduce. `uv run ruff check .`, `uv run ruff format --check .` (3277 files)
and `uv run python scripts/check-backlog-consistency.py` (168 items) all passed.
No ledger amendment or test change is justified by these results; inventory
delta is zero. Supplied base resolves locally. Previous job evidence remains
preserved below, distinct from these freshly executed checks.

Read accepted ADR-081226-a66b and ADR-085, and proposed ADR-081. No architecture
waiver applies: preserve Goal -> Graph -> Run -> NodeRun -> Attempt and canonical
per-principal enforcement. Fresh inspection of the load profile confirms its
explicit representative-traffic and telemetry gaps; run_soak.py:744–755 always
rejects host preflight as exact-RC evidence. The executed rate-limit regression
at tests/test_soak_promotion_gates.py:439–487 demonstrates independent allowances
for the same identity on two production middleware instances, not deployed
cluster safety. No long-running deployment was executed by this follow-up.
Production reachability confirmed: maistro_server/main.py:648 installs
RateLimitMiddleware; api/rate_limit.py:90–98 constructs its own in-memory
limiter. The schedule probe at run_soak.py:1067–1092 cancels an unexecuted
queued Run, so it cannot prove physical Attempt uniqueness/recovery.
BACKLOG.md:267–279 already classifies the replica-budget gap as engine-116
(gap-spec); this round neither files remote issues nor invents a competing
rate-limit authority.

### Fresh acceptance disposition

| Criterion | This follow-up's evidence |
|---|---|
| Representative RC workload | UNVERIFIED: profile explicitly omits multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal/background workloads. |
| At least two production replicas | UNVERIFIED: two ASGI middleware instances in executed tests are not deployed replicas. |
| Sustained saturation, queues, reclaim, retries, leaks | UNVERIFIED: no sustained deployment run; six database-dependent tests skipped. |
| No duplicate physical work and Goal reconciliation | UNVERIFIED: inspected schedule admission probe cancels its Run before execution. |
| Rate/security/degraded behavior resists replica selection | Negative evidence: executed production-middleware regression obtains [200,200,429] independently on both instances for each identity class. Deployed security/degraded behavior UNVERIFIED. |
| Full telemetry with explicit thresholds | UNVERIFIED: profile documents incomplete production worker/pool/lease and application-loop observations; no fresh production telemetry. |
| Active-work restart, drain, fencing and recovery | UNVERIFIED: no active Attempt kill/restart performed. |
| Long soak of exact RC/configuration | UNVERIFIED: executed promotion-gate tests reject host preflight even at four hours; no immutable promotion artifact/configuration was exercised. |
| Classify load findings before promotion | Partial: engine-116 records the observed allowance gap, and backlog gate passed. Completeness for a new RC soak UNVERIFIED. |
| Hash-bound machine/human production evidence | UNVERIFIED: this checkpoint is local validation metadata, not a new RC evidence pack. |

Disposition: BLOCKED. Only this checkpoint changed; no tests, inventory notes,
ledger, code, or runtime configuration changed. No failed validation commands.
No current driver check logs were available; the supplied historical log was
inspected and its failure was not reproducible. No full-tree pytest or live
PostgreSQL/production soak was run. No need to amend an already matching ledger.
Next action requires a designated immutable RC/configuration, completion of the
representative workload and canonical cluster-budget decision, then a >=4-hour
production soak with full telemetry and physical-work recovery evidence.
Repeated preflight/unit validation cannot supply that evidence.
Progress: checked 1, local validation/handoff done 1, acceptance complete 0,
skipped issues 0, errors 0. Preserve the existing branch; no integration approval.

## Previous job checkpoint (preserved)

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
