# Issue #860 — b68a76ae repair checkpoint

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, clean starting HEAD `e355fcf769fc4ed65914a2159b120e7ac7cec8be`.
- Dispatch snapshot: `/home/dev/maistro/jobs/b68a76ae0fc447bd96eb73fdd927add5/dispatch-context.json`.
- Files eligible for repair: `quality/vulture-baseline.json` only if the exact
  mandated scan provides evidence; issue-860 soak runner/tests and adjacent
  production files only for an evidenced defect; this validation note.
- Read-only acceptance context: repository instructions, relevant ADRs, issue
  body, supplied prior result and failure log, existing load profile and evidence.
- No GitHub mutations, new issue enumeration, scheduler/authorization changes,
  or unrelated branch-diff repairs.

## Initial results and ambiguity

- Starting HEAD matches dispatch; `git status --short` is empty.
- Current job directory has no `check-*.log` files. The supplied historical
  failure and fresh validation will be used instead of assuming driver success.
- Prior result reports BLOCKED, not a develop-sync conflict. Do not infer that
  a merge or a fresh local preflight would supply exact release-candidate evidence.
- `uv sync --locked --extra dev`: PASS.
- Exact requested vulture scan: PASS, 1,326 reviewed identities / 1,326 findings,
  zero unclassified and never-allowlist findings. No ledger amendment justified.
- Historical check-3 failed the schema-fence test (24 actual DDL statements,
  21 expected). Fresh `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**; failure does not reproduce. Current independent
  expectations include all three validation audit columns. Database skips are
  not evidence of live concurrent DDL safety.
- A first dispatch parser assumed `issue` was an object, but it is an integer;
  corrected navigation to `sources[0].data` and read the full issue body.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **100 passed**.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,195 files).
- `uv run python scripts/check-merge-markers.py`: PASS.
- All validation commands used 1,200-second tool timeouts.

## Architecture reconciliation

Read accepted ADRs 081426-1f7c (Attempt is physical execution identity),
081626-f383 (canonical store owns execution leases/fences), 082526-b36a
(opt-in TTL/renewal/reclaim), and 073126-c4e1 (immutable RC/release process).
Admission uniqueness is not physical-work uniqueness. No alternate scheduler,
lease authority, Goal store or authentication path is warranted. Local middleware
budgets are explicitly process-local, so their tests cannot waive the issue's
replica-selection requirement. No selected immutable RC image/package/configuration
was supplied; publishing or selecting a new RC is not this repair's authority.

## Acceptance audit

These are fresh source reviews and executions, not adoption of prior PASS claims.
No deployed soak was executed in this repair.

| Criterion | Evidence and remaining boundary |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` identifies missing multi-user/Workspace, Graph fan-out, successful tool/model, Canvas and Goal/background workloads. Current runner mix at `scripts/soak/run_soak.py:1372–1395` is limited to health, task submission, receipts and metrics with one credential. |
| At least two production application replicas | **UNVERIFIED deployed RC.** `deploy/docker-compose.prod.yml:26–77` defines two services; boot-contract tests pass, not a deployed experiment. |
| Sustained saturation, queue, leases, retry, memory/descriptor/process leaks and restart | **UNVERIFIED.** Executed current evaluator against `evidence/m3a-round30-shakedown.json`: 420.08 seconds, failed `sustain_duration` and `exact_rc_artifact`. Sampler unit tests do not substitute for sustained observations. |
| Exactly-once/fenced physical work, including Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the schedule probe's unexecuted Run. Receipt/admission deduplication is not physical Attempt execution evidence. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; independent allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439–493` with real production middleware: the same identity obtains `[200, 200, 429]` independently from each instance. `rate_limit.py:32–37` explicitly documents process-local budgets. Backpressure and local security tests pass, but cannot prove shared enforcement. |
| Complete telemetry with thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410–1424` measures driver loop lag, not application loop lag. No current sustained saturation/worker/reclaim/leak/error evidence. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427–1489` records process exit/rejoin and HTTP counters without an observed active-Attempt physical-work oracle. No new kill/restart experiment executed. |
| Long exact-RC/configuration soak | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:730–741` always rejects host preflight as exact RC. Current CLI regression tests prove even synthetic four-hour preflight evidence cannot pass. No selected immutable RC/configuration supplied and no four-hour run performed. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** Existing load-profile classifications were read, but no new complete load/classification audit performed; GitHub mutations prohibited. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED current RC.** Historical artifacts and this checkpoint are not an exact-RC evidence pack. |

Historical-evidence evaluation was executed via `uv run python -`, importing
current `run_soak.py` and asserting the exact failed-gate set, duration below
`PROMOTION_MIN_SUSTAIN_SECONDS`, and current `preflight_artifact_check().ok`
being false. All assertions passed; this is evidence rejection, not a new soak.

## Disposition

**BLOCKED.** The specific historical CI failure does not reproduce and vulture
already matches its reviewed ledger. No source, test or ledger repair is justified
by current evidence. Only this checkpoint changes; no tests added/removed, so no
inventory delta is needed. No conflicts or uncommitted incoming work required
salvage. All inherited history remains intact. No full-tree/full-package test
claim, GitHub mutation, gate waiver, or integration approval is made.

Next: provide the selected immutable RC/configuration, complete representative
workloads and application/Attempt telemetry through the canonical execution spine,
reconcile replica-selection rate semantics, then run the required long soak.
Repeating the already-passing CI repair checks cannot resolve these prerequisites.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: selected RC and missing production acceptance evidence}.

