---
inventory-delta:
  packages/maistro-core/tests: -3
---
# fix-1522-merge-73a4

Merge-forward of PR #1522 (`chatgpt/m1-1079-egress-composition-v2`) onto
`develop` at `a1b8f4a1`. `develop` had continued evolving the same
Binding/credential-authority machinery this PR touches, producing a real
add/add conflict on
`packages/maistro-core/tests/test_model_egress_container_composition.py`:
both branches independently created a file at that same path.

The two versions were not the same tests written twice -- each covered real,
non-overlapping ground:

- This PR's side (4 collected tests) covered the `litellm_key` ->
  `bootstrap_model_bindings()` credential-backfill path end to end, including
  provider-metadata/cost assertions and the `MAISTRO_LLM_API_KEY` transport
  wiring.
- `develop`'s side (6 collected tests) added `BindingDisabled` bootstrap
  coverage (an operator-disabled declaration stays registered but refuses
  resolution) and a `CostAwareRouter` selection path (an unpinned Binding
  routed through the Container's populated registry), plus two
  `ModelBindingConfig` field-validator tests (`_require_scope_identity`,
  `_reject_empty_refs`) that this PR's side didn't have yet.

The two were hand-merged into one file that keeps every scenario from both
sides (6 collected tests total): this PR's `litellm_key`/metadata/API-key
assertions, plus `develop`'s disabled-Binding test, router-selection
sub-scenario, and the two `ModelBindingConfig` validator tests.

That union is smaller than the sum of what each side's own inventory notes
already recorded for this path (`pr-1079-model-egress-composition.md` and
`pr-1091-m1-1079-model-egress-composition.md` each record +3 for an earlier
revision of this PR's side; `issue-1086-canvas-visual-quality-egress.md`
records `develop`'s own +2 here) -- because both notes were written against a
version of this file that existed on only one branch. An add/add conflict on
the same path is exactly the non-additive case
`scripts/check-suite-inventory.py`'s own docstring calls out: two branches
that both "add" tests at one path do not sum, because the merge is a
reconciliation of one file, not two. The -3 recorded here is the correction
for that double-counting, not a real loss of coverage -- every test either
side had is still collected after the merge.

Two more merge-artifact fixes landed in the same commit, neither of which
changed any collected count:

- `packages/maistro-core/src/maistro/container.py`
  (`build_node_resolver`) and
  `packages/hive-conductor/backend/adapters/maistro_core.py`
  (`MaistroCoreBridge.start`) each silently merged into a duplicate keyword
  argument (`provider_registry`/`llm_router` in the former,
  `model_bindings` in the latter) -- git's 3-way merge accepted both
  branches' additions at slightly different surrounding lines without ever
  emitting conflict markers, which is a real `SyntaxError`
  (`packages/maistro-core/src/maistro/container.py`, a "duplicate argument")
  the inventory gate could never have caught on its own; only running the
  suite surfaced it. Neither file was in the diff's list of conflicted
  paths.
- `packages/hive-conductor/backend/config.py` carried two independently
  added settings for the same concept -- this PR's `maistro_model_bindings`
  (wired into `AgentConfig.model_bindings` and covered by
  `test_maistro_core_adapter.py`) and `develop`'s bare `model_bindings`
  (read by `routes/canvas.py`'s `_quality_binding_id` and covered by
  `test_canvas_model_egress.py`, which never itself flowed into the
  Container). Consolidated onto `maistro_model_bindings` (the one actually
  wired into `AgentConfig`, and the naming every other embedded-Container
  setting in this file already follows); updated `routes/canvas.py`,
  `.env.example`, and the `SimpleNamespace` fakes in
  `test_canvas_model_egress.py` and `test_maistro_core_adapter.py` to match.
  `test_canvas_model_egress.py`'s fixture also had no credential registered
  for its Binding at all, so it would have hit `CredentialScopeError` the
  moment the merged `credential_refs`-required check
  (`credentials/router.py`, already shared by both branches before this
  round) applied to it; added a matching `CredentialRecord` and
  `credential_refs` to the fixture's Binding. Neither change adds or removes
  a test.
