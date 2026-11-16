# Issue #1862 — production loading before generic composition-guard collection, revalidated at lane head

Lane L1862 (implement + verify), job `1a2aec658d754c9ba3f9344245ce27fa`,
worktree `~/Git/wt/auto-1862`, branch `auto-1862`, base = head before this
note = `afb8659ac4829ad8d674fdd7e92ad24e2a4dc2a9` (develop tip). Every piece
of evidence below was executed in this lane against that exact revision;
nothing is inherited from prior-round claims.

## Reconciliation with the landed implementation

#1862 was filed 2026-10-03 against develop `8c8fc8d67`, where both guards
still derived `shipped_kinds()` from process-local `list_kinds()`. PR #1935
(commit `4010e69f6`, 2026-10-04, under parent issue #1082) landed the shared
helper `packages/maistro-core/tests/graph/nodes/_production_registration.py`
and the universe proof `test_production_registration_universe.py` before this
lane ran; `git merge-base --is-ancestor 4010e69f6 HEAD` holds at this head.
This lane therefore performed focused revalidation of every #1862 acceptance
criterion at the merged revision. No code repair was needed; no test count
moved, so this note records no `inventory-delta`.

## Acceptance criteria -> executed evidence

- **Fresh interpreter, only the two guard modules, all eleven creative
  registrations**: `uv run pytest
  packages/maistro-core/tests/graph/nodes/test_node_composition.py
  packages/maistro-core/tests/graph/nodes/test_container_node_composition.py
  -v --tb=short` -> **137 passed**; all eleven `creative.*` identities appear
  in both sweeps' parametrizations. The audited counterfactual executes as a
  regression: `test_a_bare_core_import_misses_what_loading_adds` (passed), and
  the same probe run by hand at this head reports the core-only selection at
  **19 non-test kinds with zero `creative.*`**.
- **Same loading boundary, no per-kind hand-written assertions**: both guard
  files import `_production_registration` (the only loading path either uses);
  the Container identity sweep parametrizes over the reconciled universe
  (`test_the_container_resolver_composes_every_production_kind`, 30 params)
  and `test_the_composition_sweeps_use_this_universe` +
  `test_the_declaring_sweep_is_a_subset_of_the_reconciled_universe` pin both
  sweeps to that one universe.
- **Collection-order independence**: node-composition alone -> 99 passed;
  container alone -> 38 passed; reversed file order -> 137 passed; a broader
  four-file selection including `test_base_contract.py` -> 162 passed; the
  full CI selection (below) -> unchanged universe. Test fixtures stay
  excluded (`test.*` filters plus the AST source scan;
  `test_test_shaped_registrations_never_enter_the_universe` passed).
- **Loader import failure is visible**: with an external `sitecustomize`
  shim raising `ImportError` on `maistro_design.creative_nodes`, collection
  of the guard file **errors** ("Interrupted: 1 error during collection") —
  no skip, no empty successful sweep. The shim lived outside the tree.
- **Negative cases**: bare-resolver refusal, named missing authority,
  synth-dag store regressions, production-wiring omission, and the #1165
  fail-closed Warden/Sentinel seam -> `-k` selection over them gives
  **34 passed** (node-composition) and **1 passed** (container seam pin).
- **CI selection unchanged**: `.github/workflows/ci.yml` `test` job still
  runs `uv run pytest packages/maistro-core/tests -v --tb=short`
  (`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`); no new job. Executed at this
  head with CI's env: **12399 passed, 890 skipped, 1 xfailed** in 345.97s,
  exit 0.

## Selected production identities at this revision

30 kinds enter the guards, all through loaded reachable production modules:
19 core through the `maistro.graph.nodes` catalog sweep (`agent.delegate_remote`,
`agent.remote_work`, `agent.spawn_harness`, `agent.synth_dag`, `airtable.poll`,
`compliance.block`, `dashboard.append_section`, `human.approve_draft`,
`human.ask_question`, `human.delegate_to_role`, `human.review_and_edit`,
`jira.poll`, `jira.wait_for_subtasks`, `llm.summarize`,
`rsi.quota_pace_trigger`, `transform.alias_keys`,
`transform.extract_field`, `transform.filter_by_type`,
`transform.format_markdown`) and the eleven creative kinds through
`maistro_design.creative_nodes` (`creative.acceptance`,
`creative.artifact_generate`, `creative.artifact_plan`,
`creative.brief_resolve`, `creative.copy_platform`, `creative.cross_critique`,
`creative.message_architecture`, `creative.publish_export`,
`creative.research_evidence`, `creative.targeted_refinement`,
`creative.visual_direction`). Captured from `--collect-only` at this head.
`maistro_design.nodes` (`design.orchestrate`, `design.consistency_eval`)
stays outside the proof under its reviewed `design-node` reachability
disposition, asserted by
`test_the_unreachable_registration_module_stays_out_of_the_proof` (passed).

## Boundary note

The issue's scope sentence names `maistro_design.creative_graph` as an entry
path; the helper imports `maistro_design.creative_nodes` — the registration
module `creative_graph` itself executes (`from .creative_nodes import ...`,
`creative_graph.py:51`) when production imports it — and
`test_the_creative_kinds_enter_through_their_real_production_module` pins
that identity. This is the same real production loading path, not a
hand-maintained kind list.
