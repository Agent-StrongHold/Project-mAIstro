# Issue #860 — current CI repair

## Latest checkpoint — job `7d8dc6e818e340e6b08c9f1df256168a`

Frozen scope: issue #860, assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`; clean starting HEAD `011688e3a20b72bd68fb3765d24e92f76045a624`,
assigned base `626683154ce9dbd521e6754cee494190c0fb29f0`. No salvage or merge
conflict present. Inspected supplied dispatch snapshot and prior result
`8c1c10c6`; no driver `check-*.log` files existed at initial inspection.
Only this existing handoff and the reproduced blank-EOF defect in
`issue-860-8c1c10c6-repair.md` change. No source, tests, inventory, runtime
configuration, ledger, grants or historical raw evidence changed.

Fresh validation (1200-second timeouts; job-local `check-*-worker.log`):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, **1336 findings / 1336 reviewed identities**, zero unclassified/never-allowlist. Scanner comparison base `56332162cf63`. No unbanked identity or dead-code repair was identified; manufacturing a ledger amendment is not justified.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 3003 files.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **61 passed in 2.42s**. No new tests, so no inventory delta required.
- `uv run python scripts/check-suite-inventory.py`: PASS, 15 suites, 27048 unique identities, no duplicate evidence.
- `uv run python scripts/check-ratchet-provenance.py` and `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Inline `uv run python` evaluated `m3a-round6-shakedown.json` with the current runner: failures are `sustain_duration` and `exact_rc_artifact`. It records 90.43 seconds and `hashes.git_head=b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned HEAD. The initial diagnostic queried the wrong top-level identity key; the appended correction reads the actual nested key. This is evidence reevaluation, **not a fresh soak**.
- `git diff --check 626683154ce9dbd521e6754cee494190c0fb29f0...HEAD` initially failed at `issue-860-8c1c10c6-repair.md:115`. Removed that single extra EOF line; `git diff --check 626683154ce9dbd521e6754cee494190c0fb29f0` then passed. This fixes a demonstrated check failure, not the missing soak.

Reviewed repository instructions and accepted ADR-085, ADR-081626-f383 and
ADR-082526-b36a. ADR-081 is Proposed, not an acceptance waiver. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and canonical lease/fence authority:
one admission or terminal Run count does not prove physical-work uniqueness.
ADR-085 principal-keying does not establish shared replica state. The stronger
#860 non-bypass criterion remains unmet rather than silently narrowed to #842's
local-enforcement contract. No competing authority or policy change introduced.

| Acceptance criterion | Executed evidence / disposition |
|---|---|
| Representative users/Workspaces and execution/product workload | **UNVERIFIED**; profile gaps at `m3a-load-profile.md:152-164` remain. |
| Two application replicas | Boot-contract tests pass; deployed exact-RC replicas **UNVERIFIED**. |
| Sustained saturation, reclaim, retry, memory/fd/process leaks | **UNVERIFIED**; historical 90.43-second run is not a long soak. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**; admission tests cannot establish execution/fencing/reconciliation under load. |
| Rate/security/degraded non-bypass by replica selection | Counterexample reproduced for authenticated and pre-auth identities by `test_replica_selection_has_an_independent_production_allowance`: same identity receives `[200,200,429]` on each replica. Production installs that middleware at `maistro_server/main.py:628`; constructor at `api/rate_limit.py:72` uses independent memory. Full RC security/degraded behavior **UNVERIFIED**. |
| Complete PostgreSQL/application-loop/worker/RSS/fd/queue/error telemetry | Process-group sampler tests pass; complete production telemetry and threshold observations **UNVERIFIED**. |
| Active-work replica kill/restart drain/fencing/recovery | **UNVERIFIED**; no new deployed failure/recovery run. |
| Long-running exact RC artifact/config soak | **UNVERIFIED / blocked**; current evaluator rejects historical artifact/duration; `run_soak.py:635-646` rejects its own host-process topology. |
| Findings filed/reclassified to earliest invariant | Complete disposition **UNVERIFIED**; no GitHub mutations permitted or performed. |
| Machine/human evidence bound to exact image/package/commit/config | Historical pack reevaluated; current qualifying RC evidence **UNVERIFIED**. |

**BLOCKED, not merge-ready.** The vulture failure does not reproduce and the
remaining block is not a develop-sync conflict. No immutable RC/configuration
was designated by this assignment; do not invent one or equate a longer host
preflight with production. Next: select the RC, complete representative workloads
and application/physical-effect oracles, resolve the replica-budget mismatch,
then run the unchanged production artifact for >=14400 seconds with active-work
failure/recovery observations. Docker availability is not claimed as a blocker;
a production soak was not executed in this bounded CI-repair round.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
1 initial validation failure repaired (diff whitespace). Commit locally only;
no push or integration approval. Existing work preserved.

---

## Historical checkpoint — job `97a26abf2d78434dbc8c424a44b1f392`

Frozen scope: #860 only, assigned `auto-860` worktree. Verified clean starting
HEAD `e28917ddb6f26f5408a0dec2a58145da68357f46` and locally resolving assigned
base `97c05e0f17e3ed72c82d76ed7eb0a0fe702883fb`. No conflict or uncommitted
salvage existed. Inspected prior job `e0312ee2` result independently; no driver
`check-*.log` files existed in this job's initial snapshot.

Fresh validation (600/1200-second command timeouts; logs in the job directory):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, **1342 findings / 1342 reviewed identities**, zero unclassified/never-allowlist. Actual comparison base `086ad770863b`; `repair-vulture.log`. No unbanked identity exists to amend or genuinely dead finding to repair.
- `uv sync --locked --extra dev`: PASS (`repair-sync.log`).
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS, 2858 files (`repair-ruff-{check,format}.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: **88 passed, 5 skipped**, missing `MAISTRO_TEST_PG_DSN` (`repair-pytest.log`). No live PostgreSQL proof claimed.
- `uv run python scripts/check-suite-inventory.py`: PASS, 14 suites (`repair-inventory.log`).
- `uv run python scripts/check-deployment-claims.py`, `uv run python scripts/check-compose-secrets.py`, `uv run python scripts/check-merge-markers.py`: PASS (`repair-deployment.log`, `repair-compose.log`, `repair-merge-markers.log`).
- Inline `uv run python` imported the current driver and evaluated the four fixed historical packs below. Each failed both `sustain_duration` and `exact_rc_artifact`, as asserted (`repair-evidence.json`). Run 6 still records **90.43 seconds**, not 14400. This is evidence evaluation, not a new soak.

Reviewed accepted ADR-085 (principal keys, not shared replica storage),
ADR-081626-f383 (durable Attempt authority and stale-writer fencing), and
ADR-082426-82c7 (occurrence-keyed Run admission). Preserve the canonical
Goal → Graph → Run → NodeRun → Attempt model: admission uniqueness cannot
stand in for physical-work or recovery proof. No authority or policy redesign.

Reachable production behavior: `maistro_server/main.py:593` installs
`RateLimitMiddleware`; `api/rate_limit.py:72` constructs an independent
in-memory limiter. Executed tests at `tests/test_soak_promotion_gates.py:435`
prove another allowance on replica 2 for the same authenticated or pre-auth
identity after exhausting replica 1. The old H3 shared-store claim is already
corrected; no cosmetic evidence edit is warranted. The reference Compose is a
local build with required external gateway configuration, not a designated
immutable RC. `scripts/soak/run_soak.py:635` rejects host-preflight equivalence.

| Acceptance criterion | Fresh evidence / disposition |
|---|---|
| Representative RC profile | PARTIAL: profile inspected; users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and background applicability remain UNVERIFIED. |
| Two application replicas | Boot-contract tests pass; deployed exact-RC replicas UNVERIFIED. |
| Sustained saturation/reclaim/retry/leaks | UNVERIFIED; no sustained run executed. |
| Physical-work uniqueness / Goal reconciliation | UNVERIFIED; admission checks and terminal Run counts do not prove execution/recovery. |
| Rate/security/degraded non-bypass | Aggregate non-bypass NOT MET: real middleware tests reproduce independent replica allowances. Full RC security/degraded behavior UNVERIFIED. |
| Complete telemetry and thresholds | Process-group sampler regression passes; full application-loop/worker/RC metrics and thresholds UNVERIFIED. |
| Active-work kill/restart and recovery | UNVERIFIED; no live replica restart executed. |
| Long exact-RC soak | NOT MET by evaluated packs; no designated exact-RC >=14400-second evidence. |
| Findings filed/reclassified | Local F11/F12 milestone classifications inspected; external filing UNVERIFIED and prohibited in this lane. |
| Hash-bound machine/human RC evidence | Historical packs evaluated; qualifying RC evidence UNVERIFIED. |

**BLOCKED**: the requested CI debt failure does not reproduce. The unresolved
block is missing production evidence plus the replica-budget contract mismatch,
not a develop-sync conflict. Only this checkpoint changes; no source, runtime
config, tests, inventory delta, ledger, grants or raw historical evidence edits.
Next: designate the immutable RC/configuration, complete representative workload
and physical-effect/telemetry oracles, resolve the replica-budget mismatch, then
soak that unchanged production artifact for >=14400 seconds. Do not substitute
another host preflight or speculative ledger amendment. Commit locally; no GitHub
mutations or integration approval. Progress: checked 1, done 0 acceptance-complete,
skipped 0 issues, errors 0 validation commands; 5 database tests skipped.

---

## Historical checkpoint — job `cdbeb34bb1d745d28f39fedf9c3bb57b`

Frozen scope: issue #860 only, assigned branch/worktree `auto-860`, clean
starting HEAD `278a8a53763fcd5dd7a76a69133ca69cf16525e8`; assigned base
`c0441cf94b9a8e58517da0f4159070b97ea6a706` verified locally. No conflicts or
uncommitted salvage were present. Prior job `30440cfa` result inspected;
no driver `check-*.log` files existed in the supplied job-directory snapshot.
Candidate edit is this checkpoint only unless fresh validation exposes a real
repair. No immutable RC image/configuration was designated in the assignment;
assumption: a host preflight cannot substitute for the required production soak.

Fresh commands, not inherited verification (1000/1200-second timeouts):

- Exact requested Vulture command: PASS, 1345 findings / 1345 reviewed identities,
  zero unclassified or never-allowlist. Actual comparison base `1e4933e2a1b7`.
  No unbanked identities exist; no ledger amendment or dead-code removal is justified.
- `uv sync --locked --extra dev`: PASS.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2859 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped** (no `MAISTRO_TEST_PG_DSN`). No live PostgreSQL proof.

Architecture reviewed: accepted ADR-085 defines principal-keyed rate limiting,
not shared state; ADR-081626-f383 defines canonical durable Attempt fences;
ADR-082426-82c7 defines occurrence-keyed Run admission, not physical-effect
uniqueness. ADR-081 is Proposed. Preserve Goal → Graph → Run → NodeRun → Attempt;
no scheduler, execution, event, store or authorization authority changes.

The prior shared-store H3 claim is already corrected in `m3a-soak-evidence.md`.
Production `RateLimitMiddleware` still constructs independent in-memory limits;
the executed middleware regression demonstrates another allowance on replica 2.
The load profile explicitly records missing users/Workspaces, Graph fan-out,
successful model/tool, Design/Canvas and Goal/background workloads. These are
real remaining acceptance gaps, not Vulture debt or merge conflicts.

Additional fresh validation (1200-second timeout):

- `uv run python scripts/check-suite-inventory.py`: PASS, all 14 suites.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-compose-secrets.py`: PASS, 8 Compose files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `git diff --check`: PASS.
- Inline `uv run python` imported the current driver and evaluated the fixed four
  historical packs: `m3a-soak-evidence.json`, `m3a-repair-validation.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`. Assertions that each fails
  both `sustain_duration` and `exact_rc_artifact` passed. Run 5/6 record 90.17 /
  90.43 seconds, not 14400. This is not a new soak.

Command outputs are in this job's tool transcript; initial Vulture output is
also `/tmp/860-vulture.log`. Inspected reachable middleware installation at
`packages/maistro-server/src/maistro_server/main.py:593`, constructor at
`api/rate_limit.py:72`, real middleware tests at
`tests/test_soak_promotion_gates.py:435`, and production Compose's two-server
reference build/external model-gateway contract. No exact-RC deployment ran.

### Acceptance disposition for this checkpoint

| Criterion | Executed evidence or remaining gap |
|---|---|
| Representative profile | PARTIAL: inspected documented request mix and gaps; RC users/Workspaces and applicable execution/product surfaces UNVERIFIED. |
| Two application replicas | Boot-contract tests pass; two deployed exact-RC replicas UNVERIFIED. |
| Sustained saturation/reclaim/retry/leaks | UNVERIFIED; no sustained run performed. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED; occurrence admission is not physical execution or recovery proof. |
| Rate/security/degraded non-bypass | Independent replica allowance reproduced by production-middleware tests; aggregate non-bypass unmet. Full RC security/degraded behavior UNVERIFIED. |
| Complete telemetry and thresholds | Sampler regression passes; application-loop/worker/RC telemetry coverage UNVERIFIED. |
| Active-work kill/restart and recovery | UNVERIFIED; no live replica restart performed. |
| Long-running exact-RC soak | All four historical packs fail duration and artifact gates; qualifying run UNVERIFIED. |
| Findings classified/filed | Local F11/F12 M3-A classifications inspected; external filing UNVERIFIED and prohibited in this lane. |
| Hash-bound machine/human evidence | Historical packs evaluated; qualifying RC evidence UNVERIFIED. |

**BLOCKED**: no evidenced CI ledger failure or sync conflict to repair. No source,
config, ledger, grant, tests or raw evidence changed; no inventory delta needed.
Only this checkpoint is committed. No GitHub mutations or integration approval.
Next: designate the immutable RC image/configuration, complete production-profile
workloads and telemetry/physical-effect oracles, resolve the replica-budget
contract mismatch, then run ≥14400 seconds on that unchanged artifact. Another
host preflight or speculative ledger amendment cannot satisfy the acceptance.
Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues,
errors 0 validation commands; 5 database tests skipped.

---

## Historical checkpoint — job `8c939288e0f948ee8ecd7c21abb76db9`

Only #860, writer CI-repair, assigned worktree `/home/dev/Git/wt/auto-860`.
Verified clean starting HEAD `cffdf7caf4427ed2f5c4737c371f162364890280`;
assigned base `b35c76e035b3ee60789f9eac3e82526e23aba2e1` resolves.
No conflict or salvage edits were present. Prior `c99b4bd1` result read;
no driver `check-*.log` files were present in the job-directory snapshot.

Fresh validation (1200-second timeouts except initial Vulture scan: 1000):

- `uv sync --locked --extra dev`: PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, **1345 findings / 1345 reviewed identities**, zero unclassified or never-allowlist. The checker reports comparison base `1e4933e2a1b7`. No actual debt mismatch exists, so **no ledger amendment or code deletion is justified**.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS, 2859 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: **88 passed, 5 skipped** (missing `MAISTRO_TEST_PG_DSN`). No live PostgreSQL proof claimed.
- `uv run python scripts/check-suite-inventory.py`: PASS, 14 suites.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-compose-secrets.py`: PASS, 8 Compose files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Inline `uv run python` imported the current runner and asserted that all four historical packs in the table below fail both duration and exact-artifact checks: PASS. Run 6 remains 90.43 seconds versus 14400 required. This is evidence evaluation, **not a fresh soak**.

Fresh transcripts are `worker-ruff-{check,format}.log`, `worker-pytest.log`,
`worker-check-*.py.log` and `worker-evidence.log` in the supplied job directory.
Initial Vulture output is in the tool transcript (also `/tmp/pi-bash-96319284b9bf785c.log`).

Re-read repository instructions, the load profile, evidence pack, current runner,
adjacent tests and production limiter. Accepted ADR-085 defines principal keys,
not shared replica state; accepted ADR-081626-f383 and ADR-082526-b36a require
canonical fencing and lease renewal/reclaim. Accepted ADR-082426-82c7 makes the
occurrence the Run admission identity, not proof of physical effects. ADR-081
remains Proposed. No alternative execution or authorization authority introduced.

The acceptance table below remains **BLOCKED**. Executed production-middleware
regressions reproduce independent allowances on both replicas for authenticated
and pre-auth identities (`rate_limit.py:25-30,72`; middleware installed in
`maistro_server/main.py:593`). The old shared-store claim is already corrected.
`run_soak.py:635-646` explicitly rejects host-preflight artifact equivalence;
no designated immutable RC image/configuration/provider manifest was supplied.
No live RC replicas, sustained workload or active-work restart ran this round.
Full profile, physical-work uniqueness, application telemetry, recovery, external
finding filing and hash-bound promotion evidence therefore remain UNVERIFIED,
not inferred from passing unit tests.

Only this checkpoint changes. No tests added, so no inventory delta is needed;
no code/runtime configuration, ledger, grants or historical evidence changed.
Commit locally; no GitHub mutations. Next: release-owner designation of the exact
RC, completion of production workload/telemetry and physical-effect oracles,
resolution of the replica-budget mismatch at the canonical policy seam, then
≥14400 seconds on that unchanged artifact/configuration. Another host preflight
or speculative ledger edit cannot resolve the block.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues,
errors 0 validation commands; 5 database tests skipped. CI debt failure did not
reproduce; issue #860 remains unresolved.

---

## Historical checkpoint — job `9ca96a35080a4b3f8c7ea6d01dc083aa`

Frozen item: #860 only, branch `auto-860`, verified clean starting HEAD
`62b69b3f500e40fa65e2ab91663e10083d3a544b`. Assigned develop base remains
`cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`; the vulture gate uses the actual
merge base `045cfdfbe3ea`. No merge conflict exists. Previous result
`617c8e0536a54be8b6a065a42827903e/result.json` was inspected, not accepted as
fresh verification. No driver `check-*.log` files were supplied in this job.

Freshly executed (logs in the supplied job directory):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0; 1,360 reviewed identities match 1,360 findings, zero unclassified/never-allowlist (`worker-vulture.log`). No ledger amendment or dead-code deletion is justified.
- `uv run ruff check .` and `uv run ruff format --check .`: both exit 0 (`worker-ruff-check.log`, `worker-ruff-format.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped** (`worker-pytest.log`). All five skips require a migrated database via `MAISTRO_TEST_PG_DSN`; this is not live PostgreSQL evidence. Includes real production-middleware replica-selection counterexamples, real task router/spine backpressure, and the live Linux child-process sampler regression.

Additional fresh checks: `uv run python scripts/check-deployment-claims.py`,
`uv run python scripts/check-execution-lifecycles.py`,
`uv run python scripts/check-merge-markers.py` and `git diff --check` all passed.
The current `failed_promotion_checks` evaluator rejected each of the four fixed
historical packs listed below for both duration and exact artifact; assertions
passed (`worker-evidence-check.json`). Run 6 still records only 90.43 seconds.
This evaluates historical evidence, not a new soak or its passing flags' validity.
Production `maistro_server/main.py:588` installs the inspected limiter.

Re-inspected production `RateLimitMiddleware` and reference Compose, the
current artifact gate, tests and load/evidence profile. The old H3 shared-store
claim is already corrected. The passing middleware regressions still demonstrate
independent replica allowances, **not** non-bypass of an aggregate principal
budget. The reference Compose declares two servers but supplies a local image
build and mutable dependency tags; the assignment does not designate an immutable
RC image/configuration. A four-hour host-process run would still fail the explicit
`exact_rc_artifact` gate and would not resolve this block.

Architecture reconciliation: accepted ADR-081226-69ee retains Graph → Run →
NodeRun → Attempt; ADR-082126-f69c makes schedules canonical Run producers, not
a second runtime. Accepted ADR-081626-f383 distinguishes durable stale-writer
fencing from lease-expiry takeover. Therefore admission counts, process rejoin and
terminal Run counts do not certify physical-work uniqueness/reclaim. ADR-081 is
Proposed, not an accepted waiver. No execution or authorization authority changes.

The ten-criterion acceptance disposition below remains **BLOCKED**. No new
production soak, multi-replica deployment, active-work restart, or external finding
filing is claimed. No code, runtime configuration, tests, inventory counts, ledgers,
grants or historical evidence changed; this checkpoint is the only tree edit.
The required next work remains designation of the exact RC/configuration, a
representative production workload and telemetry/recovery oracle, resolution of
the replica-limit mismatch, and a qualifying ≥14,400-second unchanged-artifact run.

Progress: checked 1, done 0, skipped 0 issues, errors 0 validation commands;
5 database tests skipped. Commit this checkpoint; #860 remains unresolved.

---

The following sections preserve the previous job's checkpoint and acceptance map.

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `a74f7429ba109f56529516b404abaf92faae99ea`.
- Assigned base: `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`.
- Job: `617c8e0536a54be8b6a065a42827903e`.
- Starting working tree clean; empty salvage diff preserved outside the worktree.
- Process the explicit vulture exact-debt-ledger gate, then focused existing soak/admission/persistence tests and acceptance evidence. Candidate edits are this report, `quality/vulture-baseline.json` only for observed reviewed retained identities, and source/test/inventory files only if the gate demonstrates actual dead code requiring repair. No execution-authority redesign or production rate-limit redesign is in scope.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, load profile/evidence docs, production rate middleware, adjacent persistence/task tests and relevant accepted ADRs.
- Job directory has no `check-*.log` files at initial inspection. Do not rely on historical green claims.
- Prior result reports BLOCKED; independently validate rather than infer completion.

## Assumption and stop condition

This is a writer CI-repair round, not authorization to claim a host-uvicorn preflight is an exact production RC soak. No immutable RC image/configuration is supplied in the assignment. If production evidence remains missing, record it as UNVERIFIED and hand off blocked rather than fabricate a four-hour soak or weaken gates.

## Results

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passed (exit 0): 1,360 findings, 1,360 reviewed identities, 0 unclassified, 0 never-allowlist. No unbanked identity was reported, so no source deletion or ledger amendment is justified. The historical shared-store limiter claim is already corrected at the assigned HEAD; no duplicate cosmetic repair is needed.

Focused validation passed: `uv run ruff check .`; `uv run ruff format --check .` (2,809 files); `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` (88 passed, 5 skipped in 3.28s). The five skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL validation is claimed. The passing tests include both authenticated and unauthenticated production-middleware counterexamples: replica 2 admits two more requests after the same identity exhausts replica 1.

Architecture review this round: accepted ADR-081226-a66b retains canonical Run/NodeRun/Attempt lifecycle ownership; ADR-081626-f383 requires durable Attempt fencing and explicitly distinguishes it from expiry/takeover. ADR-085 requires principal-keyed rate limits but does not establish shared replica state. ADR-081 is Proposed, not an accepted waiver of production evidence. Preserve Goal → Graph → Run → NodeRun → Attempt; neither admission uniqueness nor process exit proves physical side-effect uniqueness. No competing authority is introduced, and no acceptance criterion is waived.

Imported the current driver using `uv run python` and ran `failed_promotion_checks` over the four frozen historical packs. Assertions that each fails `sustain_duration` and `exact_rc_artifact` passed:

| Evidence file under `evidence/` | Recorded sustain seconds | Failed gates |
|---|---:|---:|
| `m3a-soak-evidence.json` | absent | 7 |
| `m3a-repair-validation.json` | absent | 7 |
| `m3a-round5-final.json` | 90.17 | 3 |
| `m3a-round6-shakedown.json` | 90.43 | 2 |

This evaluates recorded evidence, not the truth of every historical passing flag. The current driver (`scripts/soak/run_soak.py:635`) explicitly rejects exact-RC equivalence. Production `maistro_server/main.py:588` installs the middleware whose constructor allocates a separate in-memory limiter (`api/rate_limit.py:72`). The reference Compose (`deploy/docker-compose.prod.yml:26-62`) declares two application replicas, but local builds and mutable dependency tags are not an identified immutable RC.

Additional gates passed (exit 0):

- `uv run python scripts/check-deployment-claims.py`
- `uv run python scripts/check-execution-lifecycles.py` (19 discovered/classified lifecycles)
- `uv run python scripts/check-merge-markers.py`
- `git diff --check`

Fresh command output is retained in the job directory under
`/home/dev/maistro/jobs/617c8e0536a54be8b6a065a42827903e/`:
`vulture.log`, `pytest.log`, and `evidence-check.json`. The latter records the
current evaluator's failures for the four fixed historical packs; it is not a
new soak. No driver `check-*.log` files were available. These results were
executed independently, not copied from the previous BLOCKED result.

## Acceptance disposition

| Criterion | Current evidence / disposition |
|---|---|
| Representative RC profile | PARTIAL: existing profile has request mix and thresholds, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC applicability UNVERIFIED. |
| At least two application replicas | Reference Compose inspected; actual exact-RC replica deployment UNVERIFIED. ASGI instances do not count as deployed replicas. |
| Sustained saturation, queue growth, reclaim, retry, leaks | UNVERIFIED: no sustained run executed; all four historical packs rejected. Subprocess sampler regression is not long-window observation. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: profile's schedule probe admits then cancels a queued Run; admission uniqueness does not prove physical Attempt or side-effect uniqueness. |
| Rate/security/degraded behavior and replica non-bypass | NOT MET for aggregate principal allowance: executed production middleware regression proves a second allowance on the second replica for both authenticated and pre-auth identities. Full security/degraded behavior under RC load UNVERIFIED. |
| Complete metrics with explicit thresholds | PARTIAL: process-group sampler regression passes; complete application event-loop latency, worker census and RC metrics/threshold validation UNVERIFIED. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED: no replica restart executed this round; historical rejoin/terminal counts do not prove physical-work recovery. |
| Long-running exact-RC soak; rerun after runtime/config change | BLOCKED: no designated immutable RC/configuration; current runner is explicitly not a promotion runner. No four-hour exact-RC soak executed. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing F11/F12 records classify M3-A evidence defects. External filing UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical packs preserved and evaluated, but qualifying RC image/package/config hashes and soak evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not integration approval. The requested CI failure does not reproduce. The prior block is missing release evidence and an observed rate-limit contract mismatch, not a merge conflict or unbanked vulture debt. Changing the ledger or re-running a short host-process soak cannot resolve it.

Only this report changed. No new tests, no inventory delta, no source/runtime-config, ledger, grant or historical evidence edits. No GitHub mutations.

Next owner must designate immutable RC images and configuration, establish the applicable representative workload, resolve the replica aggregate-limit mismatch without a parallel authorization path, provide a production-topology runner with physical Attempt correlation and full application telemetry, then execute at least four hours on that unchanged artifact/configuration. Runtime/config changes invalidate the run.

Progress: checked 1 assigned issue; done 0 (acceptance blocked); skipped 0 issues; errors 0 executed checks; 5 PostgreSQL tests skipped. Local commit records this checkpoint; the issue remains unresolved.

## Independent checkpoint — job 407d760f58e345679d8123a765426289

Frozen scope: issue #860 only, assigned worktree `/home/dev/Git/wt/auto-860`,
starting HEAD `c0367dfb065ab01561e337018f3fd069ab708124`, supplied develop base
`94781cf6b708a385f33a9aafcbe9f83a481b6858`. Starting tree was clean; an empty
salvage patch and scope snapshot were saved in the job directory. No driver
`check-*.log` files were supplied at initial inspection. The logs below were
produced by this worker, not inherited verification claims.

### Executed checks

All commands below exited 0 on the assigned head:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **1,338 findings / 1,338 reviewed identities**, zero unclassified and zero
  never-allowlist. The gate reports its own baseline `8a4bc239fe9a`; no override
  was supplied. There is no unbanked identity to repair or authorize. No ledger
  amendment or speculative dead-code deletion is justified.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 2,917 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **92 passed, 6 skipped in 3.56s**. All skips require `MAISTRO_TEST_PG_DSN`;
  live PostgreSQL behavior is not proven by this run.
- `uv run python scripts/check-deployment-claims.py`: deployment claims pass.
- `uv run python scripts/check-execution-lifecycles.py`: 19 discovered and
  classified lifecycles.
- `uv run python scripts/check-backlog-consistency.py`: 168 items pass.
- `git diff --check 94781cf6b708a385f33a9aafcbe9f83a481b6858...HEAD`:
  no whitespace errors. The previously reported blank-at-EOF defect does not
  reproduce against the assigned base/head.

A separate `uv run python` import of the current soak evaluator rejected
`evidence/m3a-round6-shakedown.json` for `sustain_duration` and
`exact_rc_artifact`: 90.43 seconds recorded, 14,400 required. Its historical
passing flags were not independently re-proven. The current artifact check
returns `ok=false`, topology `host-uvicorn-preflight`. No new soak ran.

Fresh outputs reside under
`/home/dev/maistro/jobs/407d760f58e345679d8123a765426289/` in
`check-{vulture,ruff,format,pytest,deployment,lifecycles,backlog,diff,evidence}-worker.log`.

### Reachability and acceptance

Production `packages/maistro-server/src/maistro_server/main.py:593` installs
`RateLimitMiddleware`; its constructor at `api/rate_limit.py:72` creates a
process-local limiter. The executed tests at
`tests/test_soak_promotion_gates.py:439-488` use that production middleware and
prove both authenticated and pre-auth identities receive `[200, 200, 429]`
from each replica independently. They are ASGI counterexamples, not a deployed
multi-replica soak. Local enforcement passing does not satisfy replica-selection
non-bypass.

Accepted ADR-081226-a66b and ADR-081626-f383 preserve the canonical
Goal → Graph → Run → NodeRun → Attempt authority and durable physical fencing;
admission deduplication cannot stand in for physical-work recovery.
ADR-085 principal identity does not establish shared replica state.
ADR-083026-a91e forbids treating missing measurements as zeros. No criterion
is waived and no competing execution or authorization path is introduced.

| Issue acceptance criterion | Evidence / disposition in this checkpoint |
|---|---|
| Representative release-candidate profile | PARTIAL: `m3a-load-profile.md:152-164` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC applicability UNVERIFIED. |
| At least two application replicas | ASGI limiter instances exercised; actual supported production RC deployment UNVERIFIED. |
| Sustained saturation, queue growth, reclaim, retry, leaks and restart | UNVERIFIED: no sustained run; current evaluator rejects the historical 90.43-second pack. |
| Exactly-once admission, Goal reconciliation and fenced physical work | Local admission backpressure tests pass; cross-replica physical execution and Goal behavior UNVERIFIED. Schedule probe limitations remain documented at `m3a-load-profile.md:197-200`. |
| Security/degraded behavior and replica-selection non-bypass | NOT MET for aggregate principal allowance: executed production middleware counterexample above. Complete security/degraded behavior under RC load UNVERIFIED. |
| Required telemetry and explicit pass/fail thresholds | Process-group sampler tests pass; application-loop latency, worker census and complete RC telemetry/threshold evaluation UNVERIFIED. |
| Active-work replica kill/restart, drain and fenced recovery | UNVERIFIED: no replica killed/restarted in this checkpoint; process rejoin alone would not prove physical fencing. |
| Long-running exact RC artifact/configuration soak | NOT MET: current driver rejects exact-RC equivalence at `scripts/soak/run_soak.py:635-668`; no immutable RC image/configuration designated in this assignment, no four-hour production run. |
| Findings filed/reclassified to earliest invariant | Local backlog consistency passes; completeness of filing/reclassification UNVERIFIED. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | Historical evidence preserved and rejected by current evaluator; qualifying current RC evidence UNVERIFIED. |

### Disposition and next action

**BLOCKED.** The specified CI failure and whitespace finding do not reproduce.
The previous blocker is an unmet release-evidence contract, not a merge conflict
or scanner finding. No code, runtime configuration, tests, inventory, ledger or
grant changed; only this existing report was extended. There is no new test
inventory delta. This checkpoint is committed locally, not integration approval.

Next: designate the immutable RC artifact/configuration and representative
workload, resolve the aggregate-rate contract mismatch through the existing
security authority, then provide a production-topology runner with physical
Attempt correlation and complete application telemetry and execute at least
four hours on the unchanged artifact. Another short host-process run or ledger
edit cannot resolve this blocker.

Progress: checked 1, done 0, skipped 0 issues, errors 0 executed checks;
6 PostgreSQL tests skipped. Acceptance remains blocked; no new item started.

## Job 7c17dc01 — fresh validation of assigned head dabd9fe28984

Scope frozen to #860 in `/home/dev/Git/wt/auto-860`, starting HEAD
`dabd9fe28984252f85f463b08b597d91b68f9342`, supplied base
`30677b185400538df2aab0432c63c02d673f3d0e`. Initial worktree clean; no
merge conflict and no driver `check-*.log` files supplied. Read the frozen
issue acceptance/comments and prior result; the prior BLOCKED verdict was
not substituted for execution. Logs from this validation are in
`/home/dev/maistro/jobs/7c17dc01c78246de9f35d67c105d596e/check-*-worker.log`.

### Actual commands and outcomes

All these commands exited zero:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  1,338 findings / 1,338 reviewed identities, zero unclassified or
  never-allowlist. Its reported baseline is `94781cf6b708`, not the supplied
  diff base; no baseline override used. This matches the workflow invocation.
  **No ledger change or dead-code deletion is warranted.**
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 2,920 files already formatted.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **61 passed in 2.89s**, no skips. These are focused regressions, not a
  production deployment or a sustained soak.
- `uv run python scripts/check-deployment-claims.py`: claims pass.
- `uv run python scripts/check-execution-lifecycles.py`: 19 classified lifecycles.
- `uv run python scripts/check-backlog-consistency.py`: 168 items pass.
- `uv run python scripts/check-suite-inventory.py`: all 14 suites match;
  26,020 unique test identities, no duplicate evidence.
- `git diff --check 30677b185400538df2aab0432c63c02d673f3d0e...HEAD`:
  no whitespace defect reproduced.
- `uv run python` imported the current soak evaluator and asserted that
  `evidence/m3a-round6-shakedown.json` fails both `sustain_duration` and
  `exact_rc_artifact`. Observed duration **90.43s**, required **14,400s**;
  the current artifact check returns `ok=false`, `host-uvicorn-preflight`.

### Acceptance disposition (fresh evidence, not promotion approval)

| Criterion | Result |
|---|---|
| Representative release profile | PARTIAL: profile reviewed; user/Workspace population, Graph/tool/model/Canvas and Goal/worker workloads remain absent (`m3a-load-profile.md:152-164`). RC applicability UNVERIFIED. |
| Two production application replicas | UNVERIFIED. Tests exercise two middleware instances, not two deployed RC replicas. |
| Sustained saturation, queue/reclaim/retry, memory/descriptor/process leaks | UNVERIFIED. Historical short evidence rejected by executed evaluator; no new sustained run. |
| Admission, Goal reconciliation and no duplicate physical work | Backpressure/receipt regressions pass; physical Attempt fencing and Goal reconciliation across replicas UNVERIFIED. One occurrence admission is not physical-work proof. |
| Rate/security/degraded behavior without replica-selection bypass | NOT MET for aggregate allowance: executed `test_replica_selection_has_an_independent_production_allowance` proves `[200, 200, 429]` independently on both instances for authenticated and pre-auth identities. Complete RC-load behavior UNVERIFIED. |
| Required telemetry and thresholds | Sampler regressions pass; complete RC telemetry, application-loop latency and worker census UNVERIFIED. |
| Active-work kill/restart, drain and recovery | UNVERIFIED; no deployed replica killed/restarted in this round. |
| Long soak of exact RC artifact/configuration | NOT MET: current driver explicitly fails artifact equivalence (`run_soak.py:635-668`); historical pack fails duration too. No immutable RC designation supplied. |
| Findings filed/reclassified at earliest invariant | Local backlog consistency passes; external filing completeness UNVERIFIED. No GitHub mutation performed. |
| Machine/human hash-bound production evidence | Historical pack remains preserved with `git_head=b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head. Qualifying current RC evidence UNVERIFIED. |

Reachability checked: `maistro_server/main.py:593` installs the tested production
middleware; `api/rate_limit.py:72-76` constructs its process-local limiter.
ADR-085 (Accepted) requires principal-keyed limits; it does not prove shared
replica state. ADR-081 is Proposed, not authority to waive acceptance.
Accepted ADR-081226-a66b and ADR-081626-f383 preserve the canonical
Goal → Graph → Run → NodeRun → Attempt model and durable fencing. No new
scheduler, execution authority or authorization path is introduced to disguise
the missing production proof.

**BLOCKED**, not a CI-ledger repair. Only this existing handoff is extended;
no code/configuration/tests/ledger/grants changed, and no inventory delta is
needed. Next action is an explicitly designated immutable RC, a representative
production-topology workload with physical-work correlation and full telemetry,
and resolution of the aggregate-rate contract before the unchanged four-hour
soak. Repeating this green vulture check cannot resolve those prerequisites.
Progress: checked 1, done 0, skipped 0 issues; validation commands passed,
acceptance remains blocked. Commit this checkpoint locally; no integration
approval or issue closure.

## Job 6d3b71cd — validation of assigned head 921e6a75ca4b

Scope frozen to issue #860, branch `auto-860`, clean starting HEAD
`921e6a75ca4b0eb1ad0bd4f381191d0d64c33f80`, supplied develop base
`b0912ce590d51bcfe4944da57770575e50ae2e8a`. No conflict or uncommitted salvage
was present. This job directory supplied no `check-*.log`. The supplied older
`98a11313/check-3.log` was inspected: its 24-versus-21 DDL assertion is already
repaired in the current test by the three Gauntlet validation columns
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:174-178`). The
prior `9e70c718` result reports a provider timeout, not an acceptance result.

### Fresh executed checks

Logs are `worker-*.log` under
`/home/dev/maistro/jobs/6d3b71cd71a240b7b29cccb3edad224a/`. All commands below
exited zero; prior verification claims were not substituted for execution.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **1,332 reviewed identities / 1,332 findings**, zero unclassified or
  never-allowlist findings. Workflow arguments match `quality.yml:1013-1016`.
  The gate resolved baseline `1df433bf5ece`, not the supplied diff base; no
  override was used. There is no evidenced ledger amendment or dead-code fix.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The reported schema-fence failure does not reproduce.
  Skips are not live PostgreSQL concurrency proof.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **65 passed**, no skips. These cover admission backpressure, fail-closed soak
  gates, sampler missingness, boot cleanup and production limiter behavior.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: **3,105 files** already formatted.
- `uv run python scripts/check-deployment-claims.py`: passed.
- `uv run python scripts/check-execution-lifecycles.py`: **19** classified lifecycles.
- `uv run python scripts/check-suite-inventory.py`: **17** suites match,
  **28,173** unique identities, zero duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py`: **168** items passed.
- `git diff --check`: passed.
- A `uv run python` probe imported the current driver and evaluated preserved
  `evidence/m3a-round6-shakedown.json`. It asserted rejection for both
  `sustain_duration` (**90.43 s** against **14,400 s**) and `exact_rc_artifact`.
  `preflight_artifact_check()` returned `ok=false`, `host-uvicorn-preflight`.

### Acceptance checked against current reachable behavior

| Criterion | Evidence and disposition |
|---|---|
| Representative RC profile | PARTIAL: profile exists; `m3a-load-profile.md:152-164` explicitly lacks users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/worker coverage. RC applicability UNVERIFIED. |
| At least two application replicas | UNVERIFIED for the selected production RC. The executed tests use two ASGI middleware instances, not a deployed RC pair. |
| Sustained saturation, queues, leases, retries and leaks | UNVERIFIED. Historical short pack rejected by the executed evaluator; no sustained run in this round. |
| Admission, Goal reconciliation and no duplicate physical work | Local backpressure and probe regressions pass. Cross-replica physical Attempt fencing and Goal reconciliation UNVERIFIED; occurrence admission alone is not physical execution. |
| Security/degraded behavior without replica-selection bypass | Aggregate non-bypass is NOT PROVEN: executed `test_replica_selection_has_an_independent_production_allowance` observes `[200, 200, 429]` separately for each replica, for authenticated and pre-auth identities. Full RC-load security UNVERIFIED. |
| Required telemetry and thresholds | Sampler tests pass, but application-loop latency, worker census and complete RC threshold evaluation remain UNVERIFIED. |
| Active-work kill/restart, drain and recovery | UNVERIFIED; no replica killed/restarted here. Rejoin alone cannot prove fenced physical recovery. |
| Long-running exact RC artifact/configuration | NOT MET: current driver explicitly returns false at `scripts/soak/run_soak.py:686-697`; no immutable RC image/configuration supplied and no four-hour production run. |
| Findings filed/reclassified to earliest invariant | Local backlog consistency passes; completeness of filing/reclassification UNVERIFIED. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact hashes | Historical evidence preserved and rejected by current evaluator; qualifying current RC evidence UNVERIFIED. |

Reachability: `maistro_server/main.py:648` installs the tested production
`RateLimitMiddleware`; `api/rate_limit.py:72-77` allocates its process-local
limiter. Its documented N-times-limit semantics do not prove a shared principal
budget. Accepted ADR-085 specifies principal identity, not shared replica state;
this contract ambiguity is recorded, not silently resolved by changing policy.
Accepted ADR-081226-a66b and ADR-081626-f383 preserve the canonical
Goal → Graph → Run → NodeRun → Attempt authority. In particular, the fencing
ADR does not itself authorize expiry takeover. Accepted ADR-083026-a91e keeps
unmeasured metrics absent. No competing authority or acceptance waiver added.

**BLOCKED**, not a reproduced CI defect. Only this existing evidence checkpoint
changed; no code/configuration/tests/ledger/grants changed, so no inventory delta
is needed. Designate the immutable RC and representative workload, resolve the
rate-contract mismatch through existing security ownership, then execute an
instrumented production-topology soak with physical Attempt correlation for at
least four hours on the unchanged artifact. Another host-process shakedown or
ledger edit cannot satisfy that prerequisite. This local commit is a handoff,
not integration approval or issue closure.

Progress: checked 1, done 0, skipped 0 issues, errors 0 executed commands;
6 tests skipped. No additional item started.
