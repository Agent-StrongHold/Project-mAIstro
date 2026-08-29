---
inventory-delta:
  packages/maistro-core/tests: +2
---
# claude-issue-556-template-provenance-acs-b5cc

Two tests added to `packages/maistro-core/tests/test_graph_definitions.py`,
both for criteria of SPEC-081226-bb3a that no existing test proved:

- `test_instantiation_binds_to_an_exact_version` (**AC-3**). The nearest
  existing test asserted version numbers on one of two Nodes and never the
  content hash, so it could not distinguish provenance that pins a revision
  from provenance that merely names one.
- `test_a_graph_template_version_pins_its_nested_node_templates` (**AC-5**).
  Nothing covered this. The property holds structurally -- a GraphTemplate
  embeds Node snapshots rather than NodeTemplate references -- which is
  exactly why it is worth an executable assertion: the tempting change to
  store `(template_id, version)` and resolve at instantiation would satisfy
  every other criterion here and silently break this one.

No test was removed, and the delta is not compensating for a deletion
elsewhere. Four existing tests were **strengthened** rather than added to, so
they do not appear in the count:

- AC-1 gained the post-edit assertion that a Node still identifies the
  version it came from -- the criterion's second clause, previously checked
  only before the edit.
- AC-2 gained a second Node (the criterion says two) and an in-place mutation
  of the template, which is what makes it falsifiable at all; its fixture is
  now nested because pydantic rebuilds a top-level `dict[str, Any]` during
  validation, so a flat one passes even against a Node that aliases its
  template.
- AC-4 gained the Edge mutation the criterion names alongside the Node one,
  plus whole-template equality.
- AC-3's old home keeps its independence assertions and now carries only the
  AC-1 marker, which is the criterion it actually proves.

Every marker was mutation-verified: each has at least one mutant of
`maistro.graph.definitions` that makes its test fail for that criterion's own
reason (wrong pinned version, constant content hash, aliased nodes, aliased
edges, and a Node handed its template's live containers).
