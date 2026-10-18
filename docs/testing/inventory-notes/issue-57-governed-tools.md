---
inventory-delta:
  packages/maistro-core/tests: +14
  packages/maistro-bootstrap/tests: +3
---
# Issue 57 governed tool contracts

Adds adversarial coverage for the M2 tool boundary:

- Agent effective allowlists and unknown model-selected schemas refuse before a
  backend call.
- Host-owned JSON schemas reject missing/extra arguments and raw command text.
- High-impact tool predictions persist exact materialized arguments, provider,
  pre-state digest, policy version, and Invocation identity; mismatches append a
  durable canonical event and are not reported as success.
- The bootstrap command tool accepts only structured `argv` and executes with
  `run_argv`, never an implicit shell string.

## Verification round (2026-10-18)

Strategy-level enforcement tests added: `ReactStrategy.reason` and
`ArtificerStrategy._handle_tool_call` refuse (a) model-selected names outside
`allowed_tools`, and (b) allowed names with no host-declared schema, in both
cases before Sentinel pre-call and before any executor dispatch; an allowlisted
valid call still executes. `Agent._build_strategy_kwargs` derives
`allowed_tools` from `identity.tools` — the same declaration that builds the
model-facing tool definitions — so the model cannot widen authorization.

## Develop-sync round (2026-10-18, merge of ab8b3737f)

The preserved `origin/develop` sync conflict was resolved in place (commit
`aa4194d3d`):

- `binding_scope_policy` now carries both sides: develop's legacy-tool effect
  floor (`m1.legacy-tool-effect`) and #57's host-resolved irreversibility floor
  (`tool.reversibility`). The container's explicit composition passes this
  evaluator, so production wiring keeps both floors.
- `InvocationExecutionService.execute` adopts develop's refactored admission
  (`_admit_effect` + quota + `_settled_by_another_admission`) with #57's
  expected-effect evidence bound onto the candidate before durable admission;
  `GovernedInvocationExecutionService.invoke` forwards both
  `expected_effect` and `actor_id`.
- Both strategies adopt develop's `security_pipeline`/bounded warden context
  and fail-closed missing-Sentinel authorization, with #57's allowlist/schema
  validation layered before Sentinel dispatch; artificer repair results are
  revalidated against the host schema. The now-unused `_prepare_tool_args`
  helper was dropped.
- `test_tool_call_identity` expects the strategy-level allowlist refusal
  string: the strategy gate fires before the executor boundary by design;
  `Agent._authorize_and_invoke` keeps the same membership decision as the
  inner defense in depth.
- Governed-contract tests opt into `binding_scope_policy` explicitly: a bare
  `new_effect_context()` is an unavailable authority, not an implicit ALLOW
  (develop's #846 fail-closed composition contract).
- Added: a high-impact `ToolContract` without its prediction contract fails
  registration (`ExpectedEffectRequired`), closing criterion 9's test gap.
- The suite-inventory delta is recorded against suite roots (+11 core, +3
  bootstrap); `check-suite-inventory.py` reports all 17 suites matching.

## Gate-repair round (2026-10-18)

Cleared every quality gate the branch was failing, each at its cause:

- **Radon**: the seven new C-blocks were refactored, not granted (a grant needs
  a trunk-landed authorization first). `ToolContract.__post_init__`,
  `validate_tool_arguments`, `_validate_schema_value`,
  `GovernedToolExecutor.execute`, `ReactStrategy.reason`,
  `_execute_one_tool_call` and `agent_loop._dispatch_tool` each decomposed into
  named single-purpose helpers; behavior is preserved and the governed-contract
  and react suites pass. 145 -> 137 C-or-worse blocks.
- **Vulture**: the argv cutover's orphaned `run_command` raw-string methods are
  deleted (Protocol + both sandbox implementations), with the three test call
  sites ported to `run_argv`; `ExpectedEffectEvidence._validate_evidence` joins
  `_vulture_whitelist.py` beside `Binding._validate_binding` (Pydantic
  decorator dispatch is invisible to the scanner), which also retires the
  ledger's `invocation.py::_validate_evidence` row; the two
  `reversibility_registry` rows are stale now that `tools/contracts.py`
  constructs the registry. Ledger: 1322 -> 1318, exit 0 with no new grant.
- **Reachability**: `maistro.tools.reversibility_registry` left the baseline
  and its disposition group records the connection through
  `maistro.tools.contracts`.
- **Promotion surface**: `tools/contracts.py`,
  `capabilities/expected_effect.py` and both reversibility modules are
  *protected* in `sensitive_paths.py` rather than tolerated in the baseline, so
  no trunk grant is consumed and a candidate editing the tool gate escalates.
- **Coverage**: `binding_scope_policy`'s `tool.reversibility` floor (added in
  the develop-sync round with no committed test) is now pinned: an irreversible
  tier carried as an Invocation admission fact gets REQUIRE_APPROVAL before any
  provider dispatch, while `internal`/`reversible` tiers resolve through
  Binding scope. +3 core test cases (delta above updated +11 -> +14).

Residual scope still open on #57 (not closed by this branch):

- `GovernedToolExecutor` is library-only: no shipped production path constructs
  it yet, so shipped tool traffic does not yet produce canonical Invocation or
  expected-effect evidence.
- The shipped `TOOL_EFFECT` inventory entries in
  `quality/direct-effect-call-sites.json` (6 sites, owner `#57`:
  `hive.web_search`/`hive.browse_url` in `chat_completion.py` and
  `legacy_dag_node.py`, `browser.search_web`/`browser.browse` in
  `tool_executor.py`) remain dispositioned `MIGRATE_TO_GOVERNED_INVOCATION` and
  are unmigrated. (PR #506 counted 7; one site left the inventory with the #56
  egress work — current authoritative count is 6.)
- Issue #847 (adversarial tool-name/schema/argument tests) must close before
  #57 closes.
