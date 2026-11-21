# Issue #860 — bounded CI repair (8dd8fc06)

## Frozen scope

- Issue #860 only; supplied dispatch-context.json is the frozen evidence snapshot.
- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `2cbb8f81c1567dc9a94c6924b3d4d1057a76bdc8`; base
  `ac69535ef165ded3ca82cd3428728569de3251fa`; starting worktree clean.
- Inspect the specified Vulture gate, existing soak runner/tests/profile, relevant
  ADRs and prior failure log. Edit the Vulture ledger only if the actual scan
  requires reviewed retained identities. No speculative runtime/gate changes.
- Output file: this report. No new tests planned absent an evidenced repair.
- Current job directory has no check-*.log files. Inspect the explicitly supplied
  prior check-3.log instead; do not treat earlier pass claims as fresh validation.
- Ambiguity: assignment combines full acceptance with a narrow CI repair. Treat
  gate repair as bounded scope, and report unproven production acceptance honestly.

## Progress

Exact requested Vulture scan passed: 1323 findings, 1323 reviewed identities,
zero unclassified/never-allowlist; resolved gate baseline `3c761d14db94`.
No ledger amendment is warranted. The supplied historical check-3.log is a
schema regression failure (24 DDL statements versus 21 expected), not a Vulture
failure. Current regression validation is next. No GitHub mutations or ref updates
planned.

## Fresh validation

Commands executed with 600–1200 second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0; counts above.
- `uv run ruff check .`: exit 0, all checks passed.
- `uv run ruff format --check .`: exit 0, 3277 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: exit 0, **118 passed, 6 skipped**, 2.61 seconds.

The historical schema failure no longer reproduces: the current expectation at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175` includes the
three validation audit columns. Production `ensure_schema` takes its transaction
advisory lock before DDL at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.
Skipped live-database tests are not multi-replica validation.

## Architecture and acceptance

Read repository instructions, documentation authority map, ADR-062,
ADR-082826-b601 and ADR-085. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
ADR-062's old `run_graph` entry point is retired. The canonical consumer's
transition-as-claim and physical Attempt execution must be exercised; an admission
count alone is not physical-work fencing evidence. ADR-085's principal-keyed
limits do not establish shared replica budgets. Production middleware explicitly
uses process-local limits (`maistro_server/api/rate_limit.py:32`); that documentation
does not waive the issue's stronger replica-selection criterion.

| Acceptance criterion | Evidence and disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**: profile at `docs/testing/soak/m3a-load-profile.md:171` lists missing users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and reconciliation traffic. |
| Two production application replicas | **UNVERIFIED**: ASGI and boot-contract tests are not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | **UNVERIFIED**: no long-window production observation performed. |
| Schedule/task/Run/Attempt physical deduplication and Goal reconciliation | **UNVERIFIED**: admission uniqueness is insufficient; profile's schedule probe cancels its Run without physical execution. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED** at deployment scale, with contrary component evidence: executed `tests/test_soak_promotion_gates.py:439` observes 200/200/429 independently on both production middleware instances for the same authenticated/anonymous identity. |
| Complete telemetry with thresholds | **UNVERIFIED**: profile has partial thresholds; application-loop latency, saturation/reclaim and long-window leak evidence are absent. |
| Kill/restart during active work and recovery | **UNVERIFIED**: no production active-work recovery executed. |
| Long-running exact RC soak | **UNVERIFIED**: `scripts/soak/run_soak.py:744` rejects its host-process topology; executed promotion-gate tests preserve this rejection. Assignment does not designate an immutable production RC image/configuration. |
| Findings filed/reclassified | **UNVERIFIED**: no fresh live-load findings or remote filing; GitHub mutations prohibited. |
| Human/machine evidence tied to exact artifact/config hashes | **UNVERIFIED**: this report binds source validation to starting HEAD, not a production soak bundle. |

## Handoff

**BLOCKED** on production acceptance, not the requested Vulture gate or a merge
conflict. No ledger/source/test changes are supported by fresh evidence. Only this
report changes; no inventory delta is needed because no tests were added or changed.
Existing work is preserved. A local report commit is not integration approval.

Next: designate the immutable RC artifact/configuration, complete the representative
production workload and telemetry, resolve replica-selection budget semantics, and
execute the >=4-hour exact-RC soak with physical-work fencing and active-work recovery.
Repeating this CI repair without those prerequisites cannot complete #860.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0; next: production
soak prerequisite/owner handoff. `uv run python scripts/check-doc-links.py`
passed (2699 Markdown files, zero broken relative links); `git diff --check` passed.
