---
inventory-delta:
  packages/hive-conductor/backend/tests: +22
---
# claude-issue-340-durable-dashboard-layouts-4740

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_dashboard_layout_durability.py` — 20 tests for SPEC-082926-3b80
(#340) — plus two in `test_widget_tools.py` for the chat tool that writes the
same record.

The split is deliberate. Fifteen drive `services.dashboard_layouts` against an
injected store, because the interesting failures are ones a working store will
not produce on demand: a write that raises, and — the one the old bare `except`
could not see — a write that raises nothing and stores nothing. One runs the
whole path against a real `maistro.state.State` on a real SQLite file, closed
and reopened, because "survives container recreation" is a claim about a
restart and against a fake it would prove nothing.

Two are structural rather than behavioural: the route must not name a path
inside the package to write layouts to, and the durable save must not sit
inside `except Exception`. Both are properties of where the module points and
how it is written, which no request can observe — and the second is the exact
defect, since the call was always there and the handler is what turned its
failure into `{"ok": true}`.

Nothing was removed. Three existing tests changed rather than being added to,
because what they read no longer exists:

- `test_platform.py`'s `test_dashboard_layouts_json_valid` asserted the shape of
  `data/dashboard_layouts.json` — runtime state that was tracked in git. That
  file is gone; the layout it held ships as `demo_dashboards/pm-command-center.json`
  so the demo account sees what it saw before, and the integrity claim moved to
  the demo templates, which are image content.
- `test_widget_tools.py`'s two layout assertions read
  `routes.dashboard_layout._LAYOUTS`; they now read the record.
- `test_dashboard_layout.py::test_put_saves_layout` asserted the response was
  exactly `{"ok": true}`. It now also asserts the revision, which is what makes
  `expectedRevision` usable — a client that never sees one cannot claim one.

`conftest.py`'s autouse isolation fixture stopped redirecting a path and started
snapshotting the store, which is the same isolation one layer over.
