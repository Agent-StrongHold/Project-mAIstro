# Issue #860 — bounded repair 741717ee

## Frozen scope

- Only issue #860, assigned `auto-860` worktree; starting HEAD
  `8e8c0c86ff49f91af6effcc33cca68b2b2d596ad`, base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
- Evidence: supplied dispatch-context.json, prior result 0432a455, and failed
  check-3.log from 98a11313. No check-*.log exists in this job directory at start.
- Candidate edits frozen to this report, `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `docs/testing/inventory-notes/860-741717ee-schema-fence.md`, and
  `quality/vulture-baseline.json` only if the requested scan identifies retained debt.
- Read-only inspection: schema implementation/adjacent tests, soak harness/tests,
  repository instructions, applicable ADRs, gate scripts/workflows and dispatch evidence.
- Assumption: this is the writer CI-repair lane, not the read-only verifier lane.
  Repair actual current failures only. Historical soak claims are not acceptance evidence.

## Initial evidence

The supplied prior test log reports 24 schema statements versus 21 expected.
This must be reproduced against the assigned HEAD before changing the assertion.
The prior result explicitly leaves every release soak criterion unverified.

## Progress

Fresh checks completed with 1200-second timeouts:

- Exact requested Vulture scan: exit 0, 1323 findings / 1323 reviewed identities,
  zero unclassified and zero never-allowlist. No ledger amendment warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  exit 0, 37 passed / 6 skipped. The old failure is already repaired at this HEAD:
  the independent expected DDL list includes all three validation audit columns.
  No schema/test edit warranted; skipped PostgreSQL tests are not live-load proof.
- Logs saved in this job directory as `check-vulture.log` and `check-schema-before.log`.
- An exploratory `rg` used a nonexistent bootstrap glob; inspection continued at
  the existing server directory. This is not a validation failure.

Current state: reported CI failures are not reproducible. No code or ledger
repair is justified by these results.

## Focused validation

Executed with 1200-second timeouts (logs in the job directory):

```text
uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q
uv run ruff check .
uv run ruff format --check .
```

Results: **81 passed in 2.42s**; lint passed; **3277 files already formatted**.
`uv run python scripts/check-doc-links.py` passed (2693 Markdown files, zero
broken relative links); `git diff --check` passed.
Together with the schema run: 118 passed, 6 skipped. No tests added or modified,
so no inventory delta or inventory-note change is needed.

## Architecture and acceptance

Read repository instructions, documentation authority map, ADR-062 (including
its retired entrypoint warning), accepted ADR-082826-b601 and ADR-085. Canonical
admission/consumption must remain on Goal -> Graph -> Run -> NodeRun -> Attempt;
receipt deduplication is not evidence of fenced physical execution. No runtime,
authorization, event authority, or scheduling change is proposed.

ADR-085 requires principal-keyed limiting; it does not establish cluster-shared
state. Production explicitly documents independent per-replica allowances at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:32`. The issue's
stronger replica-selection requirement remains unresolved rather than waived.

| Acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. Read `docs/testing/soak/m3a-load-profile.md`; its remaining-gaps section excludes multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background reconciliation. |
| Two production replicas | **UNVERIFIED**. Executed ASGI/boot-contract tests, not deployed RC processes. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | **UNVERIFIED**. Passing sampler/admission checks are bounded regressions, not a sustained production experiment. |
| No duplicate physical work across schedules/tasks/Run/Attempt/Goal | **UNVERIFIED**. Executed receipt/admission regressions; these do not exercise all physical work or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED**, with contrary evidence for shared allowances: `tests/test_soak_promotion_gates.py:439` executes production middleware and observes 200/200/429 independently on both replicas for the same identity. Backpressure tests prove retryable admission 429, not a cluster-wide allowance. |
| Required production metrics and explicit thresholds | **UNVERIFIED**. Profile and sampler tests cover only partial telemetry; driver-loop lag is not application-loop lag. No full production time series captured. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests passed; no live active-work recovery experiment executed. |
| Long-running exact-RC soak | **UNVERIFIED**. `scripts/soak/run_soak.py:744` deliberately rejects host-process preflight as exact RC. Executed promotion-gate tests confirm fail-closed behavior even for long preflight duration. No immutable RC image/config designated by the assignment. |
| Findings filed/reclassified before promotion | **UNVERIFIED**. No new live-load findings claimed; GitHub mutations prohibited and not performed. |
| Machine/human soak evidence tied to artifact/config hashes | **UNVERIFIED**. This source-validation report and job logs are not hash-tied production soak evidence. |

## Handoff

**BLOCKED** on release acceptance, not on the supplied stale CI failure. Only
this report changes; existing implementation and evidence are preserved.
Next: designate the immutable RC image/config, complete representative production
workloads and telemetry, reconcile the replica-selection allowance contract,
then execute and publish the >=4-hour exact-RC soak. Repeating a passing scanner
or fabricating a ledger amendment cannot resolve these prerequisites.

Progress: checked 1 issue; done 0; skipped 0; validation errors 0. This local
commit records a handoff, not integration approval.
