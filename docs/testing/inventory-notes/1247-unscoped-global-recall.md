---
inventory-delta:
  packages/maistro-core/tests: +1
---

# Issue #1247 — unscoped recall hides org-bound globals

`list_by_scope` without agent/user/team/org used to skip the scope rule
entirely, so an org-bound global memory leaked to a caller with no org
context. One regression test drives the in-memory store, the SQLite store,
and the PostgreSQL query builder: the unbound global and a project
organization row stay visible, and the org-bound global does not.
