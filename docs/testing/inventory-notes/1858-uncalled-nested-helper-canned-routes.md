---
inventory-delta:
  tests/: +10
---
# #1858 Ignore uncalled nested-helper work when detecting canned API routes

`scripts/check-api-route-contracts.py` walked every handler-body statement
with `ast.walk`, which descends into nested function bodies. A route that
merely *defined* a helper performing a real call — `def unused():
store.write()` — and returned only constants was therefore classified as
performing real work and escaped the canned-handler finding. The return scan
had the mirror defect: a nested helper's `return build_status()` kept the
enclosing constant-only handler out of the findings even though the route's
own returns were all literals.

## Fix

Both scans now judge the handler's *executed scope* (`_walk_executed_scope`):
a statement that only defines a nested function or lambda executes that
definition — decorators, defaults, annotations, all of which Python evaluates
immediately — but not its body, which waits for an invocation the detector
does not speculate about. Class bodies still execute eagerly and are walked;
methods inside them do not. Returns are collected from the same scope
(`_own_scope_returns`). When a nested helper *is* called, the call site is a
`Call` in the handler's scope and justifies the handler there — a deliberate
lexical limit, documented in the gate: the detector does not follow into a
called helper's body, and per the issue's scope note no interprocedural
analysis was added.

## Test delta (+10, all in `tests/test_check_api_route_contracts.py`)

Seven fail before the fix, reproducible on `develop@8a4bc239f` (verified:
7 failed, 34 passed before the script change; the synthetic route
`POST /flush` with an uncalled `store.write()` helper reported `0 canned`,
exit 0):

- `_performs_real_work` is False for calls inside uncalled nested
  `def`/`async def` bodies and lambda bodies (lambda defaults still execute —
  they are evaluated when the lambda expression is, as are nested defs'
  decorators/defaults/annotations, pinned by
  `test_nested_definition_time_expressions_still_execute`);
- a class body's eager calls count but its methods' deferred calls do not;
- the #1858 synthetic route is reported canned by `_canned_handlers`, and
  `main()` rejects it end to end (exit 1, "canned route handler") with no
  disposition registered;
- a nested computed return no longer rescues a constant-only handler.

Three preserve behavior across the change (all passed before and after): a
called helper justifies its route through the call site; a nested constant
return does not condemn a handler whose own return computes; def-time
expressions of nested definitions still count as work.

The shipped tree is unchanged in classification: the gate reports OK (279
handlers, 15 audited routes, 0 canned) before and after.
