# Issue 860 CI repair checkpoint

## Frozen scope

- Assigned issue: #860 only; starting HEAD `f01554433a5c40bdf20c3ae71ef1aa276d0c5177`.
- Incoming merge parent: `8a4bc239fe9af429be9faa087916f965e9fb20f7`.
- Preserve all incoming staged changes. Backups: `../incoming-860.patch` and
  `../incoming-860-index.patch`; incoming file snapshot: `/tmp/auto-860-incoming-files.txt`.
- Repair files: conflicted `packages/maistro-server/src/maistro_server/api/tasks.py`,
  `quality/vulture-baseline.json` (explicit CI-repair exception), and this report.
- Read-only validation scope: repository instructions, relevant ADRs, issue dispatch,
  soak harness/profile/evidence/tests, adjacent task admission tests, vulture scan
  identities and their production consumers.

## Initial evidence / ambiguity

The worktree arrived in a merge with one unresolved file and staged changes from
other issues. Assumption: finish that existing merge in place, preserving both
sides' semantics, rather than fetching/restarting a resolved merge target. The
assigned starting HEAD matches. No `check-*.log` files were present in the job
directory's initial listing; prior verification is not assumed valid.

## Status

Initial exact vulture scan exited 1 (log `/tmp/auto-860-vulture.log`). Its
missing task routes and new task response/list identities are consistent with
conflict markers making the route module unparsable; resolve syntax before
classifying these as debt. A trusted-base `POLICY` deletion also appears. No
ledger amendment will be guessed from this invalid intermediate scan.

Adjacent tests inspected: `test_tasks_concurrency_backpressure.py` requires a
ceiling refusal with Retry-After; merged `test_tasks_run_identity.py` also checks
no receipt/Run/claim is retained, replay is preserved, and retry succeeds after
cancellation. Resolve with a scope-only ceiling message and shared chat retry
interval, preserving these two contracts. No new test count is needed: both
regressions already exist, including the incoming inventory note for #1828.

The first guessed ADR filename was not found; skipped in favor of the indexed
`ADR-081-deployment-backup-dr.md`. Prior job result confirms BLOCKED, but current
acceptance will be validated independently.

## Repair validation checkpoint

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2917 files.
- `git diff --check HEAD`: PASS.
- Exact vulture command after resolution: PASS, 1338 findings, zero unclassified
  or never-allowlisted findings. Log `/tmp/auto-860-vulture-resolved.log`.
- Preserved incoming ledger amendment: remove the no-longer-reported `POLICY`
  identity (one row). This is scanner bookkeeping, not proof that
  `ResourceKind.POLICY` acquired a consumer: the incoming promotion module uses
  `PromotionScope.POLICY` at line 90, which satisfies Vulture's name-based use
  tracking. No rules, grants or unrelated ledgers edited by this worker.
  `git diff --numstat MERGE_HEAD -- quality/` is empty: incoming ledgers preserved.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_tasks_run_identity.py
  packages/maistro-server/tests/api/test_tasks_idempotency.py
  tests/test_soak_promotion_gates.py -x -q`: PASS, 67 tests, two deprecation warnings.
  Log `/tmp/auto-860-focused-tests.log`. Includes live ASGI canonical ceiling,
  claim cleanup/replay/retry, real middleware independent allowances, and a real
  uv-child process-group sampler. These are not a two-replica production soak.

## Architecture reconciliation

Accepted ADR-081226-a66b reserves lifecycle ownership for Run/NodeRun/Attempt;
ADR-081626-f383 reserves fencing identity for the canonical store. This repair
only translates canonical admission refusal, adding no authority or scheduler.
ADR-081 is **Proposed**, not an accepted waiver of issue acceptance. The merged
retry convention uses `CHAT_TURN_RETRY_AFTER_S` (5 seconds instead of the lane's
prior 1 second), with a scope-only message retaining the word `ceiling`. This
runtime change itself invalidates older soak evidence.

- Full server suite: `uv run pytest packages/maistro-server/tests -x -q`: PASS,
  495 passed, 8 skipped, 22 deprecation warnings (45.65 seconds). Skips are not
  production acceptance evidence. Log `/tmp/auto-860-server-tests.log`.
- `check-backlog-consistency.py`, `check-adr-index.py`, and
  `check-convergence-matrix.py` (all via `uv run python scripts/...`): PASS.
- Local `origin/develop` resolves to the assigned base
  `d7aa2714519a2c7fa122e3abe6096870e55d2869`; quality-ledger diff against it is
  empty as well. No rows were lost by this resolution.

- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-server/tests`: PASS, 503 collected, expected 503, no duplicate
  evidence. Existing incoming inventory notes cover the merge's added tests;
  this repair adds no tests or count delta.
- Executed the current `failed_promotion_checks` against
  `docs/testing/soak/evidence/m3a-round6-shakedown.json`: exactly
  `sustain_duration` and `exact_rc_artifact` fail. The historical evidence is
  tied to `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this code, and records
  90.43 seconds versus the required 14400. `preflight_artifact_check()` also
  returns `ok=false` on current code. Assertions confirming both passed.
- Read the frozen issue comments and linked PR descriptions/reviews from
  dispatch-context.json, not from a new GitHub fetch. They provide no exact-RC
  soak or waiver of the missing acceptance criteria.

## Acceptance review (all ten criteria)

| Criterion | Current evidence and outcome |
| --- | --- |
| Representative RC workload | PARTIAL: `m3a-load-profile.md:46-69` defines a mix, but `:152-166` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas and background Goal reconciliation. Production representativeness UNVERIFIED. |
| At least two application replicas | Production Compose defines two services (`deploy/docker-compose.prod.yml:24-79`); this round ran ASGI fixtures, not those services. Production run UNVERIFIED. |
| Sustained saturation, reclaim, retry, leaks and restart | Historical duration is 90.43 seconds (`evidence/m3a-round6-shakedown.json:163-165`); current evaluator rejects it. Long-window behavior UNVERIFIED. |
| Admission, reconciliation and physical-work fencing | Canonical task admission/claim cleanup/replay/retry tests pass. No live cross-replica physical-work or Goal reconciliation validation in this round: UNVERIFIED. Admission uniqueness is not physical-work uniqueness (ADR-081626-f383). |
| Rate/security/degraded behavior cannot be bypassed by replica choice | NOT PROVEN: `tests/test_soak_promotion_gates.py:439-488` executes real middleware and reproduces fresh allowance on replica 2 for both authenticated and unauthenticated identities. `api/rate_limit.py:25-30` deliberately promises only process-local enforcement. Do not silently replace this policy or waive #860. |
| Required telemetry with thresholds | PARTIAL: profile thresholds and sampler tests exist; real uv-child RSS/FD test passes. App-loop latency, worker counts, PG contention and full long-window telemetry on the RC remain UNVERIFIED. |
| Kill/restart with drain/fencing/recovery | Historical exit/rejoin counters cannot prove physical work fencing. Production recovery on current code UNVERIFIED. |
| Long exact-RC soak | NOT MET: `scripts/soak/run_soak.py:635-668` correctly rejects the host preflight artifact. No exact artifact/config manifest or four-hour run was produced. |
| Findings classified to earliest broken milestone | Existing backlog consistency gate passes; complete classification of all load findings UNVERIFIED. No GitHub mutations performed. |
| Machine/human evidence bound to exact hashes | Historical JSON/docs exist, but code hash differs and no current RC image/config soak exists. Current promotion evidence UNVERIFIED. |

## Handoff and residual risk

**BLOCKED for #860 acceptance; merge-conflict / vulture repair complete.** This
worker changed the task route resolution and this report, and preserved the
incoming vulture prune plus every other staged merge change. No soak gates were
weakened and no new execution or authorization path was introduced.

The production Compose is explicitly a reference artifact, requires real gateway
configuration, and builds rather than identifying an immutable RC image. Running
the host emulator for longer would not fix those evidence gaps. Next owner must
select and freeze the exact RC deployment, complete the representative workloads
and physical-effect probes, reconcile the rate-limit requirement with the declared
per-process policy, and run a new >=4-hour instrumented soak after code/config freeze.

Focused validation does not certify unrelated incoming core/Hive behavior; those
changes are preserved from the merge, not reimplemented or broadly tested here.
No driver `check-*.log` files were supplied in this job directory.

Progress: checked 1 assigned issue; CI repair done 1; skipped 0 issues; acceptance
blocked 1. Preserve the local salvage patches for provenance. No push, PR update,
issue comment or closure is authorized or performed.

## Revalidation: job 2ed496624f484eddb880f6baea75f657

Frozen scope: #860 only, clean starting HEAD
`d889b33c3bec6529e09d91188816c1d2187d3cbe`, assigned develop base
`534d475e6360985a2c95d6c82869d07001e82cda`. This is a writer validation
handoff, not promotion approval. The supplied job directory contained no driver
`check-*.log` files at entry. Current worker logs are in
`/home/dev/maistro/jobs/2ed496624f484eddb880f6baea75f657/`.

### Executed validation

| Command | Current outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1338 findings match 1338 reviewed identities; zero unclassified or never-allowlisted findings. |
| Same vulture command with `RATCHET_BASE_REV=534d475e6360985a2c95d6c82869d07001e82cda` | PASS; gate resolves the comparison merge base to `8a4bc239fe9a`. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 2917 files already formatted. |
| `git diff --check 534d475e6360985a2c95d6c82869d07001e82cda...HEAD` | PASS; supplied historical whitespace failures do not reproduce. |
| `uv run pytest packages/maistro-server/tests tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | PASS: 555 passed, 8 skipped, 22 deprecation warnings, 43.65 seconds. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | PASS: 31 passed, 6 skipped. Skipped live-PostgreSQL tests are not concurrency evidence. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests` | PASS: 503 collected and expected, no duplicate evidence. |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items. |
| `uv run python scripts/check-adr-index.py` | PASS. |
| `uv run python scripts/check-convergence-matrix.py` | PASS: 52 subsystems, 1264 production modules. |

An additional `uv run python` assertion probe imported the current soak module
and evaluated the historical round-6 JSON. It confirmed failures for exactly
`sustain_duration` and `exact_rc_artifact`, 90.43 seconds against 14400 required,
a historical commit different from the assigned head, and the current
`preflight_artifact_check()` returning false. Its output is
`check-acceptance-worker.json`; this is evaluator validation, **not a new soak**.
The historical rate-limit record also predates the six-path probe: it contains
only one direct unauthenticated replica result. Reusing its stored true boolean
cannot prove current multi-replica enforcement.

### Current acceptance disposition

All ten criteria were checked against the frozen issue body, reachable code,
existing tests and evidence; previous verification claims were not presumed true.

| Criterion | Executed evidence or remaining gap |
| --- | --- |
| Representative RC load profile | PARTIAL: profile exists, but `m3a-load-profile.md:152-166` identifies missing users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and Goal/background workers. Complete representativeness UNVERIFIED. |
| At least two application replicas | Production topology tests pass; `deploy/docker-compose.prod.yml:24-79` declares two replicas. No current production deployment was exercised: UNVERIFIED. |
| Sustained saturation/reclaim/retry/leaks/restart | Current evaluator rejects historical 90.43-second evidence. Long-window production behavior UNVERIFIED. |
| Schedule/task/Run/Attempt admission, Goal reconciliation and physical-work fencing | Server tests prove local canonical ceiling refusal, cleanup, replay and retry; sampler/probe tests pass. Live cross-replica physical effects and Goal reconciliation UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance: executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes reproduces `[200, 200, 429]` independently on both real middleware instances (`tests/test_soak_promotion_gates.py:439-488`). Full production-concurrency security/degraded behavior UNVERIFIED. |
| Required telemetry and explicit thresholds | Sampler tests observe a real uv child and missing measurements. Application-loop latency, worker counts, full PG contention and long-window threshold evidence remain UNVERIFIED. |
| Kill/restart with drain/fencing/recovery | No current production kill/restart run; exit/rejoin alone does not prove physical-work fencing. UNVERIFIED. |
| Long soak of exact RC artifact/config | NOT MET: `scripts/soak/run_soak.py:635-668` rejects host preflight; historical duration fails. No immutable RC deployment/config selection supplied. |
| Findings reclassified to earliest broken milestone | Backlog consistency passes, but that does not prove complete load-finding classification. UNVERIFIED; no GitHub mutations. |
| Machine/human evidence bound to exact hashes | Historical JSON/docs exist but identify `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not current code. Current RC hash-bound soak evidence UNVERIFIED. |

### Reconciliation and handoff

Accepted ADR-081226-a66b and ADR-081626-f383 preserve canonical lifecycle and
fence ownership. Admission uniqueness is not physical-work uniqueness.
ADR-085's per-principal rate contract does not justify treating per-process
allowance as shared enforcement; `api/rate_limit.py:25-30,72-76` explicitly
implements the former. ADR-081 is Proposed, not an acceptance waiver. No
competing authority, policy change or gate weakening is introduced.

**BLOCKED remains the acceptance verdict.** The alleged vulture/whitespace
repair is no longer necessary on the assigned head. There are no unbanked
identities to review or remove, so no ledger amendment is justified. Only this
existing handoff is updated; no runtime or tests changed and no inventory delta
is needed. Existing work is preserved.

Next action requires a frozen exact RC image/configuration and an owner decision
reconciling replica-selection rate semantics, followed by complete representative
workloads, physical-effect/recovery probes and a fresh instrumented >=4-hour
production soak. Running this host emulator longer or repeating CI-repair jobs
cannot satisfy those prerequisites. Do not infer release readiness from the
passing unit/ASGI/static checks.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
validation-command errors 0; blocked 1. This locally committed handoff records
partial progress, not completion of #860.

## Revalidation and production-artifact round: job 3bea1dffd22d46ed9b0c9ec86ef197af

Frozen scope: #860 only; starting HEAD `ad9b17cb9d25b4fab82799f6cc206a23e323234c`
(verified), develop base `3b8e090fe5316bb9c4f28a3ba6b66d24a4d53401`. The supplied
job directory again contained no `check-*.log` files; every deterministic check
was re-executed fresh. Docker is reachable in this environment (rootless daemon
socket `unix:///run/user/1000/docker.sock`; the default `/var/run/docker.sock`
is stale), which every prior round's "no RC artifact establishable here"
conclusion failed to try.

### What this round executed that no prior round did

The exact production artifact `deploy/docker-compose.prod.yml` was brought up
from the assigned head (compose project `m3a860`): nginx 1.27 LB on
127.0.0.1:18080 -> two maistro-server replicas built from `ad9b17cb9` (image ids
in evidence) -> pgvector pg17 primary + streaming hot standby + redis 7. `docker
compose config` renders fine when the documented `.env` inputs are supplied —
the prior "interpolation fails on LITELLM_API_KEY" blocker was an unsupplied
environment, not a defect. Replication is genuinely streaming
(`pg_stat_replication` = walreceiver/streaming/async; replica in recovery).
Identity evidence: `docs/testing/soak/evidence/m3a-round7-prodstack-identity.json`.

### Genuine defect found and repaired

`scripts/soak/run_soak.py` built its claim-probe Schedule without
`actor_principal_id`; canonical Run creation validates it
(`packages/maistro-core/src/maistro/runs/model.py:321`), so the promotion gate
`exactly_once_schedule_occurrence` failed admission on every occurrence against
current code — observed live (`failures: ["actor_principal_id is required"]`)
before the fix. Repair: supply the `soak-claim-actor` fixture principal, same
wiring as `packages/maistro-core/tests/scheduling/test_pg_admission.py:56`. No
gate weakened; the phase becomes executable again. No tests added, no inventory
delta (`check-suite-inventory.py` re-run: match).

### Production-artifact evidence recorded this round

- Exactly-once task admission through the LB: 12 concurrent identical
  submissions -> 12x202, exactly 1 distinct run_id
  (`m3a-round7-prodstack-quick-probes.json`).
- Rate limiting on the artifact: per-process enforcement confirmed (60 rpm /
  burst 10 per replica — `security/resource_policy.py:16-17`); one ip-identity
  exhausted replica 1's burst then obtained a fresh 10-pass allowance on replica
  2 ~0.25 s later; principal through the LB got 20 passes = 10+10 across the
  replica limiters; 429s carry Retry-After and X-RateLimit-Remaining: 0;
  /metrics gated 401 for unauthenticated AND authenticated callers. The
  aggregate allowance provably scales with replica selection — the issue's
  "cannot be bypassed by replica selection" criterion is NOT met by the
  documented per-process design and needs an owner decision (shared-store
  budget), not a silent change.
- Sustained round A (30 rps documented mix, production-untuned): records the
  profile-vs-artifact mismatch (authenticated share 429-walled at baseline
  limits), the deliberate readiness-503 degraded semantics with an open LLM
  circuit (`api/health.py:228-247`, #365/#1567), and the full degraded
  execution path: admission 202 -> claim -> Attempt -> provider failure ->
  circuit opens after 5 failures/60 s -> task terminalized `failed`.
- Sustained round B (production-limit-aware profile, corrected client):
  2755 requests / 360 s, zero transport errors; 177/177 admissions with
  receipts; replica 2 SIGTERM-drain restarted at t=144 (3.5 s) with seamless LB
  failover and rejoin by t<=150; after a 90 s settle every admitted run_id
  appears exactly once in `canonical_runs` (0 duplicate rows), all terminal,
  whole spine 661 rows 0 non-terminal; RSS/FD/process counts flat; PG sessions
  12-13, no waiting locks; replication intact.
- Exactly-once schedule occurrence on the artifact: two OS processes raced
  `admit_due` for one pinned occurrence — same-container and cross-physical-
  replica forms — exactly 1 Run created, loser reported `already_fired`
  (`m3a-round7-prodstack-schedule-occurrence-race.json`).

### Gates re-run at the post-repair head

`uv run ruff check .` PASS; `uv run ruff format --check .` PASS (3003 files);
`git diff --check 3b8e090f...HEAD` PASS; exact vulture command PASS (1336
reviewed identities = 1336 findings, no amendment needed); `uv run pytest
tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`
PASS (60 tests); `check-suite-inventory.py --suite
packages/maistro-server/tests` PASS; `check-backlog-consistency.py` PASS.

### Acceptance disposition after this round

Advanced from UNVERIFIED to production-artifact evidence: two deployed
replicas exercised; kill/restart drain/failover/recovery with zero
loss/duplication (360 s window); exactly-once task admission and schedule
occurrence (incl. cross-replica fencing); per-process rate-limit behavior and
its replica-selection bypass, now demonstrated on the artifact rather than only
ASGI fixtures; PG/latency/RSS/FD telemetry with recorded values; streaming
replication; no leak signal within the window. Still unmet and NOT resolvable
by this worker: (1) promotion requires >=4 h on a frozen, selected immutable RC
artifact — this round's images are locally built from the head, windows are
360 s, and the harness's `exact_rc_artifact`/`sustain_duration` gates correctly
still fail; (2) successful tool/model calls are impossible here (no provider
keys in the environment's gateway), so representative successful-workload
classes, multi-user/Workspace spread, Graph fan-out, Canvas and background Goal
reconciliation remain unproven; (3) the replica-selection rate-limit criterion
conflicts with the documented per-process design and needs an owner/ADR
decision; (4) filing findings upstream is prohibited to this worker (no GitHub
mutations).

**Verdict: BLOCKED for promotion acceptance; this round's repairs and evidence
are complete and committed.** Another CI-repair round on this tree cannot
advance acceptance; the next step is operational (freeze the RC artifact and
run the >=4 h instrumented soak with a working model gateway) plus one design
decision (shared rate-limit budget vs per-process semantics for the
replica-selection criterion).

Progress: checked 1 issue; harness repairs done 1; production-artifact evidence
rounds 4; skipped 0; validation-command errors 0; promotion-blocked 1.
