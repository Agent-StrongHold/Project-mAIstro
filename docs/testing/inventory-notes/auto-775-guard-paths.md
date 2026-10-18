---
inventory-delta:
  packages/maistro-design/tests: +10
---
# auto-775-guard-paths — creative stage guard coverage (#775 repair)

Ten new collected cases in
`packages/maistro-design/tests/test_creative_graph.py` covering the guard
paths of the creative-graph nodes that the happy-path executor runs never
reach, closing the diff-coverage gate failure on
`maistro_design/creative_nodes.py` (55.3% of changed branch arcs < 80%) and
the lazy creative-graph re-export branch of `maistro_design/__init__.py`:

- `CreativeBriefResolve` refusals: launch payload missing each canonical
  identity field, and identity without a shared creative context; plus
  resolution succeeding without a blackboard (persistence is a service, not a
  precondition).
- `CreativeMessageArchitecture` emitting its decision with no blackboard
  attached (the `_record_shared_stage` skip path).
- `CreativeVisualDirection` refusing a shared context without a Design System
  reference.
- `CreativeArtifactPlan` refusing a context with no artifact requests.
- `CreativeArtifactGenerate` refusing, one refusal per required input: no
  `request_id`, no persisted shared context (canonical-retry fallback with no
  blackboard), no persisted message decision, no persisted visual decision —
  and generating successfully once both decisions exist even without a
  blackboard (the durable artifact record is persistence, not generation
  input).
- `CreativeCrossCritique` naming every unplanned branch plus decision
  divergence; ignoring non-artifact and malformed annotations (non-JSON,
  non-mapping) while counting well-formed ones; seeing zero records with no
  blackboard.
- The package `__getattr__` lazy fall-through resolving `plan_creative_graph`,
  `run_creative_graph`, and `CreativeGraphPlan` to exactly the canonical
  `maistro_design.creative_graph` objects.

Also in this change (no node-ID delta): the
`test_importer.py::test_plain_text_never_blocks` property alphabet dropped
the digit category — the scanner's bounded leetspeak folding
(`normalize_for_detection`) blocks digit-substituted keyword spellings
(`ja1lbreak`) BY DESIGN, so hypothesis could synthesize exactly such
spellings and fail the property. Modified generator, same node ID.
