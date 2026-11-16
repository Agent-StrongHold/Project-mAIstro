# Issue #1084 validation handoff

This is a bounded evidence handoff on the assigned branch, not an implementation fix or merge approval. The dispatched starting head was `0824db5f3e4201390c252129a02be1555026902b`; the worktree was clean before validation.

## CI repair findings

- The assigned vulture scan, `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, reports 1,297 reviewed identities and 1,297 findings against base `bcd7acb7fd66`; it has no unbanked identities. No ledger edit is warranted.
- The CI Pyright job installs Pyright before checking `packages/maistro-core/src` and passes its output through `scripts/check-pyright-report.py --baseline 21` (`.github/workflows/quality.yml`, lines 2508–2545). In this worktree, the first replay could not start because Pyright was not installed. After installing the CI analyzer (`uv pip install pyright`, version 1.1.414), the exact analysis and report check completed with 13 errors against baseline 21. The check passed. The reported errors are within the existing allowance, so there is no reproduced Pyright regression to repair.
- Supplied checks also show Ruff, format, package-scoped suites and inventory checks passed (job `check-1.log` through `check-7.log`). These logs are supplemental; they do not prove the full issue acceptance.

## Remaining acceptance blockers

The implementation remains incomplete and should not be considered merge-ready for issue #1084:

- The actual admitted Run workspace does not join the Invocation workspace. Prior executed acceptance probe recorded `run-ws=e891d5433cda` vs `invocation-ws=default`. In `packages/maistro-core/src/maistro/capabilities/invocation.py:869-876`, Invocation workspace is populated from `binding.workspace_id` (line 873); the coordinated #1824 gateway-credential provisioning is required to repair this scope without weakening Binding authority.
- The `run_task` conductor path still lacks authenticated actor propagation: `packages/maistro-core/src/maistro/agents/conductor.py:120-165` accepts the governed call but does not pass `actor_id` to `governed_egress.complete`. The same-file identity work is owned by sibling #1870 and must not be overwritten or duplicated without coordination.
- Consequently the complete same-request authenticated actor / Workspace / Agent / Run / NodeRun / Attempt / active Binding / Provider / Invocation / security decision / usage join is not proven. Other broad acceptance criteria (later-materialized Agents, incremental streaming lifecycle, dashboard analysis, zero-effect refusal matrix and real configured-startup provider evidence) are not established by these checks and remain unverified.

The above boundaries follow accepted ADR-081226-6b46, which requires Workspace-scoped Bindings and Invocation records correlated to Workspace, Run, NodeRun and Attempt, with Provider selection inside Binding permissions. No source, tests, inventory, quality ledger, workflow, or authorization grant were changed in this handoff.

## Validation run

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — pass; baseline and findings both 1,297.
- `uv pip install pyright` — installed CI analyzer 1.1.414.
- `uv run pyright --outputjson packages/maistro-core/src` plus `uv run python scripts/check-pyright-report.py ... --baseline 21 --exit-code ...` — pass; 13 errors, below baseline 21.
- Supplied job logs `check-1.log`–`check-7.log` — Ruff, format, package tests and inventory checks report success.
