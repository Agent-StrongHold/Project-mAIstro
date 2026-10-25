# Issue #860 — round 160 validation

## Scope and starting state

Processed only issue #860 in the assigned `auto-860` worktree. Exact starting
HEAD `cfa27d7af4bb3d30ebaa88a2bf2942621d3d322e`, develop base
`833a98a9112612d1dd2557db234b6e4dacd8d0e4`. The tree was clean on entry (no
uncommitted work to salvage). The job directory contains no `check-*.log`
files, so no driver verifier log was available; every result below is a fresh
command run in this worktree.

This is a writer validation/repair round, not promotion approval. No GitHub
mutation, no issue closure, no gate weakening, no ledger edit.

## Real repair: develop sync

The branch had merged develop at `bcd7acb7fd660090736f6f06a1e01a200b391a30` and
was two commits behind `origin/develop` (`833a98a9112612d1dd2557db234b6e4dacd8d0e4`,
`Classify folded_notes acceptance evidence as branch-independent (#2336)` plus
`Complete branch-independence migration: machine-derived baselines as
branch-independent evidence (#2334)`).

Those two develop commits change `scripts/check-autonomous-merge.py`,
`quality/branch-independence.json`, `tests/test_autonomous_merge_policy_inputs.py`
and `tests/test_autonomous_merge_quality_classes.py`. Because the branch's
merge base was older, the candidate diff (`--base 833a98a --head cfa27d7af`)
misattributed develop's own commits to the branch:

- before merge: `risk=red`, `red_reasons=[trusted CI/eval surface changed:
  scripts/check-autonomous-merge.py, trusted quality policy/legacy surface
  changed (specification): quality/branch-independence.json]`, plus
  `test definition removed` integrity reasons for the new develop tests.

The branch did not modify those files relative to the merge base
(`git diff --quiet bcd7acb7f HEAD -- <file>` was SAME for all four), so the
merge was clean. After `git merge origin/develop`:

- `risk=yellow`, `red_reasons=[]`; the only yellow reasons are the branch's own
  persistence surface (`pg_learnings.py`) and its test
  (`test_pg_learnings.py`). The misattributed red reasons and the spurious
  removed-test integrity reasons are gone.

New HEAD: `5cc4c24d4920a426289984e2aada1129e9c346e3`.

## Fresh validation

All commands ran in the assigned worktree with long timeouts.

| Command | Result |
|---|---|
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 84 passed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | 21 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 PostgreSQL-dependent skips |
| `uv run pytest tests/test_autonomous_merge_quality_classes.py tests/test_autonomous_merge_policy_inputs.py -x -q` | 35 passed |
| `uv run pytest packages/maistro-core/tests/backlog/test_markdown_migration.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | 163 passed, 6 skipped |
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | 3504 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | 21 suites, 34,461 unique identities, 0 duplicates |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1297 reviewed identities / 1297 findings, unclassified 0, never-allowlist 0 |
| `uv run python scripts/check-autonomous-merge.py --base 833a98a --head HEAD` | risk=yellow, red_reasons=[], eligible=true, autonomous=false |
| `uv run python scripts/check-branch-independence.py` | PASS |
| `uv run python scripts/check-ratchet-provenance.py` | 0 lifecycle violations; 54 consumers have provenance |
| `uv run python scripts/check-backlog-consistency.py` | PASS |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `uv run python scripts/check-deployment-claims.py` | PASS |
| `uv run python scripts/check-compose-secrets.py` | PASS |
| `uv run python scripts/check-doc-links.py` | PASS |
| `uv run python scripts/check-promotion-surface.py` | PASS |
| `uv run python scripts/check-image-pins.py` | PASS |

No tests were added, so no inventory-note delta is required. No `quality/*.json`
ledger was edited.

## Acceptance disposition (unchanged from prior rounds)

| Issue #860 criterion | Evidence / status |
|---|---|
| Representative supported RC workload (users/Workspaces, mix, fan-out, schedules, queue, tool/model, Design/Canvas, workers) | **UNVERIFIED**: `docs/testing/soak/m3a-load-profile.md` still lists the missing classes; no selected RC/configuration supplied. |
| At least two supported production application replicas | **UNVERIFIED**: the passing gates use two in-process ASGI apps, not deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, memory/descriptor/process leaks, shutdown | **UNVERIFIED**: no qualifying long production observation; six schema integration tests skip. |
| No duplicate physical work across replicas (schedule/task/Run/Attempt admission, Goal reconciliation) | **UNVERIFIED**: admission/accounting probes do not observe physical Attempts under production concurrency; the schedule probe cancels its queued Run. |
| Rate/security/degraded behavior not bypassable by replica selection | **NOT PROVEN at production scope**: `rate_limit.py` constructs a process-local limiter; two-replica probes reproduce independent allowances. No shared-budget contract or deployed ingress test supplied. |
| PostgreSQL/query/lock, application-loop, worker/process/RSS/FD, queue/error telemetry with thresholds | **UNVERIFIED at promotion grade**: sampler regressions pass, but no exact-RC telemetry series. |
| Kill/restart during active work, drain/fencing/recovery without loss/duplication | **UNVERIFIED**: no production Attempt interrupted this round. |
| Long soak of the exact RC artifact/configuration, rerun after changes | **BLOCKED**: `scripts/soak/run_soak.py:744` unconditionally returns `exact_rc_artifact.ok=false` for the host-process preflight, and `PROMOTION_MIN_SUSTAIN_SECONDS=14_400` exceeds every historical run (max 420.1 s). No immutable RC artifact/configuration was designated for execution. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED for completeness**: no GitHub mutation permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for promotion**: this report binds local validation to starting HEAD, not a promoted image/config and sustained observations. |

## Architecture reconciliation

Accepted ADRs (ADR-081226-69ee, ADR-081226-a66b, ADR-081626-f383,
ADR-082526-b36a) preserve the canonical `Goal -> Graph -> Run -> NodeRun ->
Attempt` model and durable lease fencing/reclaim authority. The develop sync
adds no competing scheduler, Goal store, event authority or authorization path.
The accepted lease contract guarantees stale-writer rejection, not blanket
exactly-once physical side effects; issue #860 still requires observations at
those boundaries. ADR-081 is Proposed, not accepted authority. No soak gate was
weakened and no evidence was fabricated.

## Handoff

**BLOCKED for issue acceptance.** The concrete repair this round is the develop
sync, which removes the autonomous-merge red misclassification. All focused
gates pass. The remaining blocker is production evidence, not code: an
owner-selected immutable RC artifact and normalized configuration, a
representative workload with physical-work and telemetry oracles, a
replica-selection rate-budget decision, and a qualifying long soak including
active-work failure injection. Runtime/config changes require a new soak.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production soak}`.
Local commit records the completed validation item, not integration approval.
