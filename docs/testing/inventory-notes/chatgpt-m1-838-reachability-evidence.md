---
inventory-delta:
  tests/: +6
---

# #838 reachability source-universe classification tests

Six collected cases in `tests/test_reachability_source_universe.py`, none of
which had an inventory note yet when the branch opened. The branch's first two
(from the fail-closed-guard commit) pin the guard itself: an undeclared
`frontend/server`-style tree fails closed instead of escaping analysis, and a
declared one participates in the flat-app graph with reachable and disconnected
modules distinguished.

The next two pin the classification semantics the guard forced once it ran
against the real tree — vendored immutable suites
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

The repair commit adds the last two, pinning the third classification the
guard forced on CI once `npm ci` had materialized `node_modules` in both
frontends before the combined-suite pytest step: an installed dependency tree
that ships Python (`flatted`'s `python/flatted.py`) is outside the authored
source universe — its bytes belong to the lockfiles — and that classification
does not swallow the guard: authored, undeclared code beside the install tree
still fails closed, with the vendored file absent from the indictment. Without
it, the source universe differed between a bare checkout and an installed one,
and the gate ratcheted on install state instead of on code.

## Why this delta is +22 and not +6

Six of the twenty-two are this branch's own six cases above. The other sixteen
are absorbed, not authored: develop's `#982`/`#865`/`#800` window added 16
collected `tests/` node IDs without recording deltas, and develop's own `test`
job could not catch that because on push events it fails earlier at its
ratchet-behavior tests (base resolves to HEAD), so the suite-inventory step
never ran there. Every PR update-branching onto `3d783e74` inherits the same
+16 — observed on another PR's CI at 19:28Z as `DRIFT tests/: expected 3020,
collected 3036`. Recording it here is the ledger's designed repair — the
note's delta is whatever makes the sum come out right — and it self-corrects:
when develop records its own +16, re-running `--update` on this branch after
the next base move returns this delta to +6.


(Correction 2026-09-02: an earlier revision recorded +22 = +6 own + 16
absorbed from develop's #800 gap. The trunk heal #1031 also recorded that
+16, double-counting it; this note now records only the branch's own +6.)
