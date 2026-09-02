---
inventory-delta:
  tests/: +4
---

# #838 reachability source-universe classification tests

Four collected cases in `tests/test_reachability_source_universe.py`, none of
which had an inventory note yet. The branch's first two (from the
fail-closed-guard commit) pin the guard itself: an undeclared
`frontend/server`-style tree fails closed instead of escaping analysis, and a
declared one participates in the flat-app graph with reachable and disconnected
modules distinguished.

The repair adds the other two, pinning the classification semantics the guard
forced once it ran against the real tree — vendored immutable suites
(`packages/hive-conductor/cage`, `eval`), the department DAG corpus
(`packages/hive-conductor/dags`), the canvas migration environment
(`packages/maistro-canvas/frontend/alembic`), and the book-maker POC backend
surfaces with no runtime path (`server/config.py`, `models`, `orchestrator`,
`templates`):

- a file explicitly classified outside the graph inside an otherwise-declared
  flat application is removed from the module universe rather than reported
  unreachable (it is not baseline debt);
- an immutable vendored tree declared as a whole tree is classified, not
  silently omitted — the guard still fails closed on any unclassified sibling.
