# Issue #57 repair checkpoint — dc83ca2d

## Frozen scope
- Issue #57 only, branch auto-57, starting HEAD bc72c8a0c08899a1b908da668441579146069df7; supplied develop base 2014ab888c0bff4541a10cc2a808e021e95cb404.
- Worktree /home/dev/Git/wt/auto-57. Started clean; no salvage diff existed. No driver check-*.log files were supplied in the job directory, so all acceptance validation below was executed fresh in this round.
- Prior round (458985fd) ended BLOCKED on: #847 state=open, a SECURITY.md drift claim, and the model-egress gate. This round resolved each with fresh evidence; no develop sync conflict occurred (branch already merged develop 161dedc06 at 18da8110e; divergence from origin/develop is 158 ahead / 24 behind by design of the lane).

## Fresh executed evidence (this round, every command run here)
- `uv sync --locked --extra dev` — venv already in canonical state (checked 218 packages, no changes).
- `uv run ruff check .` — All checks passed. `uv run ruff format --check .` — 3490 files already formatted.
- Core adversarial subset (tools, capabilities, agents incl. tool_schema_boundary/react/builders_learning/artificer/spec, sentinel audit): **1583 passed, 12 skipped** (Playwright/Postgres-DSN env-gated), 1 known fake-process warning.
- Hive governed-tools subset (test_governed_tools, test_legacy_dag_node, test_agent_model_tools, test_maistro_core_adapter): **112 passed**.
- Bootstrap package: **255 passed, 7 skipped** (Windows-only escape proof + Docker/builders-image env-gated). Live backend parity remains environment-limited.
- Architecture gate tests (tests/test_check_direct_effects.py, tests/test_check_model_egress.py): **74 passed**.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI-exact, quality.yml:1526): exit 0 — 1302 reviewed identities / 1298 findings, no unbanked debt.
- `check-direct-effects.py`: exit 0 — census 51 sites (CANONICAL_INVOCATION=2, MODEL_EFFECT=35, PM_POLLING_EFFECT=10, TOOL_EFFECT=4), every site dispositioned.
- `check-model-egress.py`: exit 0 — 12 reachable escapes are explicitly dispositioned "awaiting #56 migration" (M1 #56-owned), 7 unreachable, 1 approved Provider boundary; "no candidate-approved expansion". Not a #57 blocker.
- `check-security-inventory.py`, `check-convergence-matrix.py`, `check-suite-inventory.py`: all exit 0.
- Live GitHub (read-only `gh api`): #847 state=open (updated 2026-10-07T12:55:04Z).

## Findings resolved this round
1. **SECURITY.md drift — does not reproduce.** SECURITY.md:35 (layer-4 row) now states governed tool contracts construct `ReversibilityRegistry` and resolve host-owned classifications before canonical Invocation dispatch, and distinguishes this from Sentinel approval gating (#346). Verified by reading the file; no edit needed.
2. **Criterion 10 historical seven-site equivalence — now proven with evidence.** PR #506's seven sites map to: chat_completion.py `_tool_web_search`/`_tool_browse_url` now delegate to `services.governed_tools.governed_web_search`/`governed_browse_url` (canonical seam, verified at chat_completion.py:1335/1351); graph_runner.py's two sites moved into legacy_dag_node.py, which wraps calls in `effect_context.invocations.invoke` and refuses callers without NodeContext identity; tool_executor.py's two sites are dispositioned provider backends beneath canonical Invocations (quality/direct-effect-call-sites.json, owner #57, rationale recorded); pm_runner.py `_run_browser_driven` is retired from production (no `_run_browser_driven` remains under packages/). The passing direct-effects gate validates dispositions against the AST census.
3. **Stale "CI pending" finding — CI on 4329ebeaf completed**: 25 success / 4 skipped / 1 failure. The failure is the Coverage gate ("Coverage gate (publish-set floor + diff coverage)", PR #2169) dying at the **combine** step with "Event loop is closed" annotations — the diff-coverage floor step never ran; infra flake, not branch-caused. 4329ebeaf is an ancestor of HEAD; current head bc72c8a0c is not on the remote (writer does not push), so remote CI for the exact head is UNVERIFIED by lane design.

## Criterion 12 substance check (#847)
Branch-level substance of #847 is comprehensively present and tested on this branch:
- Undeclared-tool refusal before provider dispatch for model-selected AND strategy-authored calls (`GovernedToolExecutor._admit_call` allowlist; test_tool_schema_boundary.py; ReAct/builders_learning adversarial tests).
- `AgentSpec.tools_allowed`/`write_scopes` removed rather than left misleading (agent_spec.py:97, "Security: #847 removed the unused fields"), with ADR-004 amended (commit 69a449eb3).
- BuildersLearning Frank/Mason strategy-authored effects retired (builders_learning.py:1/59: supplied tool_executor deliberately not consumed).
- Typed missing-schema denial (`UnknownToolSchema`), unsupported schema types refused, host contract validation of legacy materialized arguments.
- Scoped authorization-denied audit events before Sentinel pre_call (`maistro/security/sentinel/audit.py:25/51`, explicitly citing #847), with hive adapter audit threading pinned (d6b618be0).
- Command-capable backends behind structured argv contracts (bootstrap tests green); legacy DAG tool path requires NodeContext and traverses canonical Invocation.
What no lane can produce: the GitHub event "#847 closed". Issue closure is a maintainer action; GitHub mutation is prohibited for this worker. #847 remains open as of this round's live check.

## Acceptance status
Criteria 1–11: proven with fresh executed evidence this round (see table in 458985fd note; re-validated). Environment-limited residuals: 6 live Docker/backend tests skipped, PostgreSQL-reopen parity needs DSN, autonomous cross-process recovery races — all documented, none branch-caused.
Criterion 12: branch-side substance (adversarial tool-name/schema/argument enforcement and tests) proven; the closure event itself is external, maintainer-owned sequencing. Record as handoff condition, not a code defect.

## Handoff
No production, test, or ledger change was justified by this round's evidence: no gate failed, no drift reproduced, no unbanked identity appeared. No tests added → no suite-inventory delta required. Work committed as this note only. Verdict MERGE-READY as **writer handoff only — never integration approval**: merging remains gated on maintainer sequencing of #847 closure (criterion 12) and remote CI on the pushed head. No push, PR, issue, or ledger action performed.

Progress: checked 1 assigned issue; 3 prior findings re-verified and closed (2 non-reproducing/stale, 1 external); 0 skipped items; 0 failed validation commands.
