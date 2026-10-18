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

Residual scope still open on #57 (not closed by this branch; superseded by the
production-wiring, model-egress-seam, and re-verification rounds below):

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

## CI-repair round (2026-10-18)

CI on head `8e03f9ff8` failed exactly one root cause across two jobs: the
`test` job's `pytest packages/hive-conductor/backend/tests` step and the
Coverage gate's diff-coverage run both failed on
`test_agent_model_tools.py::test_boot_agent_denies_unlisted_model_tool_before_provider`
(3 params). The branch's strategy-level allowlist gate refuses an unlisted
model-selected tool before Sentinel pre-call with
`Error: tool 'X' is not in the Agent allowlist`, while the hive-conductor test
pinned the inner `Agent._authorize_and_invoke` message. The gate derives
`allowed_tools` from `frozenset(self.identity.tools)` (`base.py:_build_strategy_kwargs`)
— the same declaration the test pins — so the repair updates the expectation
to the earlier refusal; the direct strategy-widening test (which exercises the
inner boundary via `tool_executor(...)`) keeps the undeclared-tool message and
still passes. No production code changed in this round; no test counts
changed (40 passed in the file locally, 111 across the six core/bootstrap
suites touched by the branch). `check-suite-inventory.py` reports 17/17
suites matching at this head.

## Production wiring round (2026-10-18)

Closed the verifier's criteria 1-2 and 10 gaps: the governed tool seam now has
a shipped constructor and the six `TOOL_EFFECT` inventory sites no longer sit
on `MIGRATE_TO_GOVERNED_INVOCATION`:

- **`services/governed_tools.py` (new)** is the production wiring: host-owned
  `ToolContractRegistry` for `web_search`/`browse_url`/`clarify` (schemas,
  `internal` ADR-050 tiers, one `hive.tool` capability), a workspace-scoped
  immutable Binding registered through `register_boot_binding`, a fail-closed
  `live_tool_context()` that re-reads the Run/NodeRun/Attempt from the store
  (the `AdmittedModelCalls` pattern), and the late-bound provider backend.
- **Boot Agent tools** (`admitted_tool_executor`, bridge now passes the
  container) execute through `GovernedToolExecutor`: the tool effect itself
  becomes a canonical Invocation carrying the registry tier as an admission
  fact, with the model sub-effect nested as before.
- **Chat web tools** (`_tool_web_search`/`_tool_browse_url`) call the governed
  helpers; their direct `services.tool_executor` call sites are gone from the
  inventory.
- **Legacy DAG tool nodes**: the no-NodeContext compatibility branch -- the one
  remaining path that executed shipped tool effects with no Invocation at all
  -- is retired (fails the node); compat tests now supply canonical identity,
  and a new test pins the refusal.
- **`GovernedToolExecutor.execute` gained `effect_scope`**: the caller's
  logical tool-call identity (ToolCall id et al.) so two logical calls with
  identical arguments inside one Attempt are distinct effects while a retry of
  the same call replays; the scope cannot widen authorization and the argument
  digest still binds the evidence. Without it the boot seam would have
  falsely deduplicated distinct ToolCalls.
- Ledger: the two chat `TOOL_EFFECT` sites left the inventory; the legacy and
  BrowserClient sites and the new backend sites are
  `INTENTIONAL_LIBRARY/INFRASTRUCTURE` owner #57 with provider-backend
  rationales (the `execute_model_chat` arrangement). Two gate tests prove a
  newly introduced raw `web_search`/`BrowserClient` call site is rejected by
  the direct-effect audit (criterion 11).
- CONVERGENCE-MATRIX and the reachability disposition now describe the shipped
  constructor instead of claiming test-only wiring.

Validation this round: full hive-conductor backend suite 3666 passed / 20
skipped; maistro-core tools+effect-context suites pass; ruff check/format
clean; mypy (7-package CI set) clean; vulture (exit 0, no new debt), radon
(137 blocks, no regressions), promotion surface, direct-effects, reachability
x4, and suite-inventory gates all pass.

## Model-egress seam round (2026-10-18)

The production-wiring head passed the gates the round listed but failed one
it did not run: `scripts/check-model-egress.py` (the quality.yml
`check-model-egress` step) exited 1 — `services.governed_tools` had become a
NEW direct model-egress module because `_hive_tool_backend` re-listed the raw
hive implementations with direct `tool_executor.clarify(...)` calls, matching
the curated census triple `MODEL_EFFECT:hive.clarify`. A new model-egress
caller is frozen against the trusted base and needs a separately landed
authorization (two-merge rule) — not carryable by this branch, and grant edits
are out of scope.

Repair: the governed seam's provider backend delegates to the one shipped
dispatcher, `services.tool_executor.dispatch_tool` (the arrangement the
trusted base's boot path already used beneath `admitted_tool_executor`), so
admission (contracts, allowlist, tier, Binding, Invocation) stays above the
dispatcher while the census population returns to the trusted 20. The three
`governed_tools.py` backend call-site rows left the direct-effect ledger
(sites no longer exist; `--update` pruned exactly those three, 54 -> 51);
the chat/legacy/BrowserClient dispositions are unchanged. Boot-agent tool
tests keep passing unchanged because they patch `services.tool_executor`
module attributes, which `dispatch_tool` resolves at call time. New census
pins in `tests/test_check_model_egress.py` (+2, see
`auto-57-model-egress-seam.md`): the clarify wrapper triple counts any new
caller, and the shipped `governed_tools.py` performs no census model egress
(fails against `6abcbb367`, passes after).

Residual on #57: issue #847 remains open (its strategy/schema/argument
adversarial coverage largely landed here and in prior rounds, but closure is
an issue action this lane cannot take); `BuildersLearningStrategy` shell and
GitHub effects remain #847's outstanding scope.

## Re-verification round (2026-10-18, head daf58eec3)

No code changed: the assigned head re-validated green on every deterministic
battery, executed fresh this round (not inherited from prior claims):

- Gates exit 0: vulture (ledger 1322 -> 1318, no new debt), model-egress
  (20 callers, governed seam absent from the census), direct-effects
  (51 sites, all dispositioned; 4 TOOL_EFFECT as provider backends),
  reachability + dispositions, radon (137 blocks), promotion-surface,
  convergence-matrix, durable-tables, ratchet-provenance,
  shipped-surface-truth, suite-inventory (17/17), backlog.
- `ruff check` + `ruff format --check` clean; mypy 7-package CI set Success
  (902 files).
- maistro-core 15380 passed / 1073 skipped / 3 xfailed; hive-conductor
  backend 3666 passed / 20 skipped; gate tests 74 passed; bootstrap command
  contract 40 passed.
- Criteria 1-11 re-checked against production code (wired constructor at
  `services/governed_tools.py`, bridge passes it at
  `adapters/maistro_core.py:255`, chat/legacy seams migrated, legacy
  no-NodeContext branch refused) and against the tests named above.
- Criterion 12 remains the sole open item: closing #847 is an owner/integrator
  action outside this lane's authority; #847's own residual scope
  (`BuildersLearningStrategy` shell/GitHub bypass) is not landed here.

## Repair round (2026-10-18, head 019df24c9)

No production or test code changed: this round re-validated the assigned head
from scratch and pinned the criterion-12 blocker to exact evidence so the
integrator can sequence the close. Fresh results (this round's own runs, not
inherited):

- Gates exit 0: vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`, ledger 1322 -> 1318 findings), ratchet-provenance,
  shipped-surface-truth, direct-effects (51 sites, 4 TOOL_EFFECT all
  dispositioned provider backends owner #57), model-egress, reachability +
  dispositions, convergence-matrix, promotion-surface, suite-inventory (17/17),
  backlog, radon (137 -> 137); `ruff check` and `ruff format --check` clean;
  `mypy --strict packages/maistro-core/src` Success (792 files).
- Suites: maistro-core 15380 passed / 1073 skipped / 3 xfailed; hive-conductor
  backend 3666 passed / 20 skipped; maistro-bootstrap 236 passed / 7 skipped;
  root direct-effect/model-egress gate tests 74 passed.
- Criteria 1-11 re-proven against production code at this head (wired
  constructor `services/governed_tools.py` -> `GovernedToolExecutor.execute`;
  bridge passes `admitted_tool_executor` at `adapters/maistro_core.py:255`;
  chat web tools call `governed_web_search`/`governed_browse_url`
  (`chat_completion.py:1280,1296`); legacy DAG tool nodes run inside their
  Invocation with the no-NodeContext branch refused;
  `base.py:_build_strategy_kwargs` enforces `frozenset(identity.tools)`;
  bootstrap `run_command` is argv-only through `run_argv`).

Criterion 12 blocker, pinned at this head (#847 open; closure is a prohibited
GitHub mutation for this lane, and its residual scope lives in files outside
this lane's frozen surfaces):

- `agents/strategies/builders_learning.py:165-235` — the Frank/Mason strategy
  still invokes `tool_executor("shell", {"command": ...})` and
  `tool_executor("github", ...)` directly, with raw shell text (pipes, `2>&1`)
  and no allowlist/contract admission: exactly the #847 strategy bypass.
- `agents/spec/agent_spec.py:117-130` — `AgentSpec.tools_allowed` and
  `write_scopes` are declared and auto-populated by `with_defaults()` but no
  production reader enforces them (the only other `write_scopes` is an
  unrelated field on the trust-boundary model): the misleading
  security-looking fields #847 must consume canonically or remove.
- The strategy-level allowlist refusal (`react.py` / artificer
  `strategy.py`) returns an error string before `Sentinel.pre_call` and emits
  no scoped authorization-denied audit event: #847's named observability gap.
- #847's adversarial-test checklist is therefore incomplete on this branch
  (no BuildersLearning bypass test, no `tools_allowed`/`write_scopes` test),
  so #847 cannot even be closed from tests landed here.

Integrator sequencing to unblock: implement #847's residual scope in its own
lane/PR (files above; relations #840, #1202), close #847 from its adversarial
tests, then close #57. Criteria 1-11 of #57 are proven at head 019df24c9.
