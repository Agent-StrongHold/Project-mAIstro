---
inventory-delta:
  tests/: +4
  packages/hive-conductor/backend/tests: -5
---
# auto-465 repair

The shipped-surface detector now covers Starlette `add_websocket_route` registrations
and OAuth-style security GET handlers. Three regression nodes prove discovery and
fail-closed matrix coverage for both supported registration shapes. A fourth node
proves selected README status prose is checked against its matrix disposition.

The Design preview tests retain the validation and unavailable-render contract but
remove assertions that accepted an in-memory pending/completed job with an
unresolvable URL. A route regression also proves status polling returns 501 rather
than exposing a fabricated lifecycle.
