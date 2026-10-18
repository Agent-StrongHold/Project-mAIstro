---
inventory-delta:
  packages/maistro-core/tests: +2
---

# Issue #790 canonical loop-kind authority fence

New fitness suite
`packages/maistro-core/tests/fitness/test_canonical_loop_kind_authority.py`
(2 collected node IDs) implementing the runtime-registry half of #788 Wave 1,
Gate A: "CI contract tests fail if a product introduces a competing
Goal/Rubric/Run/eval identity." It is the enforcement named by
`SPEC-092926-7a02` (`tests:` front matter), which landed in the same change.
`ADR-092926-7a01`'s own `tests:` front matter names the complementary
*runtime* fence
`packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py`,
which landed on develop (this branch's develop sync carries it); the ADR stays
`Proposed`, and its ratification path is its merge to develop, not this suite.

1. `test_no_competing_loop_kind_registration` — walks production Python
   (`packages/*/src` plus the six governed flat roots — `hive-conductor/
   backend`, `maistro-turing/backend`, `maistro-canvas/frontend/server`, and
   `hive-conductor/{cage,dags,eval}` — tests excluded) for
   `register(<string>, ...)` calls whose first argument is a reserved loop
   slug (`goal(s)`, `rubric(s)`, `run(s)`, `eval(s)/evaluation(s)`,
   case-insensitive) outside the canonical ontology module
   (`packages/maistro-core/src/maistro/ontology/`). Passes on the current
   tree: nothing registers those kinds yet (#791 lands the canonical Rubric),
   and nothing outside `maistro-core` imports the ontology at all. The walk
   covers the governed product roots, not `extensions/*/src`; the
   reserved-slug property holds tree-wide today regardless.
2. `test_fence_detects_a_synthetic_competing_registration` — negative
   control: the same detector run against a tmp_path tree registers the fact
   the guard can fire (a synthetic `Goal` kind trips, in both the literal and
   the module-constant shape; a `Widget` control passes), so the fence is not
   decoration.

Also repaired in the same change: the #990 suite docstring claimed an
"#796 (Evolve/RSI consumer guards)" artifact that does not exist anywhere in
the tree; the docstring now says the #796 mapping owns its guards, and points
at the (now real) #790 fence instead. No guard logic in that suite changed.

`Pack`/`Fence` are intentionally not reserved slugs — they are loop
contracts (a Graph/skill bundle of one Run; a decision on a waiting
NodeRun), not ontology kinds.
