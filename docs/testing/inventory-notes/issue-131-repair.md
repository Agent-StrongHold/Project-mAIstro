---
inventory-delta:
  packages/maistro-core/tests: +1
  packages/maistro-server/tests: +1
---
# Issue #131 repair

Added one core integration case proving a concurrent terminalized chat burst is
swept to the configured retention window, and one server endpoint case proving a
pre-routing admission transition failure compensates its already-persisted Run.
Existing chat admission coverage was also strengthened to invoke the public
terminal sweep after a concurrent burst; it changes no collected test count.
