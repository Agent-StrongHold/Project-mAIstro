---
inventory-delta:
  tests/: +10
---
# fix-m1-1136-scope-review

Ten new tests in `tests/test_check_execution_lifecycle_scope_review.py`,
fixing six more real gaps in `check-execution-lifecycles.py`'s static
Literal/Enum discovery found in PR #1316's review round 3, all reproduced as
failures against the pre-fix scanner before being fixed:

- a helper reassigned later in the same scope (`Values = Literal[...];
  RunStatus = Values; Values = str`) no longer retroactively erases the
  earlier alias's already-resolved vocabulary, and the reverse ordering
  (referencing a helper before it is defined) still finds nothing rather than
  inventing a lifecycle;
- a quoted PEP 604 union operand (`Literal[...] | "Literal['failed']"`) is
  unwrapped the same way a whole annotation already is;
- a typing-form import (`Literal as L`) that is shadowed by a later,
  unrelated import or a same-named parameter is no longer treated as
  `typing.Literal`;
- a class body is no longer treated as part of the lexical enclosing-scope
  chain for its own nested classes or methods -- a same-named class
  attribute in `Outer` can no longer shadow the real module- or
  function-level vocabulary a nested `Outer.Inner`/`Outer.method` reference
  actually resolves to at runtime;
- a `Literal[PENDING, RUNNING, FAILED]` built from `Final`-typed string
  constants is resolved instead of silently contributing nothing;
- `stage`/`ExecutionStage`-shaped names are recognized as status-shaped,
  matching the existing `phase`/`state`/`status`/`lifecycle` hints.

No tests removed or renamed.
