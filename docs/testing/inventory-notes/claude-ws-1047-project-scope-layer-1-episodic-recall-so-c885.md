---
inventory-delta:
  packages/maistro-core/tests: +12
---
# claude-ws-1047-project-scope-layer-1-episodic-recall-so-c885

Twelve new node IDs, all additions, none removed (#1047, partial).

- `tests/memory/test_context_assembly.py::TestLayer1IsProjectScoped` (+10):
  one agent id with AGENT-scope memories in Projects A and B, over the
  in-memory and SQLite episodic stores, with and without a query (the ranked
  and the `list_by_scope` paths). `assemble(project_id="B")` recalls only B's
  memory; a blank project keeps both; a memory with no project is not
  recalled under a named one.
- `tests/memory/test_ranked_recall.py::TestRankingGoesThroughTheProtocol::test_layer1_sends_the_project_to_the_store`
  (+2): both recall paths hand the project to the store rather than
  filtering after the read.
