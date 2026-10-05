---
inventory-delta:
  tests/: +15
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

## Test delta (+15, all in `tests/test_check_api_route_contracts.py`)

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

Eight preserve behavior across the change (all passed before and after): a
called helper justifies its route through the call site; a nested constant
return does not condemn a handler whose own return computes; def-time
expressions of nested definitions still count as work.

The shipped tree is unchanged in classification: the gate reports OK (279
handlers, 15 audited routes, 0 canned) before and after.

## Repair round: review findings on the executed-scope model

The PR review produced two model errors, both reproduced failing on the
pre-repair head before this round's script change:

- **Postponed annotations (PEP 563).** 44/46 shipped route modules set
  `from __future__ import annotations`, which stores every annotation as a
  string: a call inside a nested def's annotation never executes. The walk
  still counted it, so a constant-only handler with
  `def helper(value: marker()): ...` escaped the gate. Fix: `_handlers`
  detects the mode (`_postpones_annotations`) and erases annotations at the
  parse boundary (`_drop_postponed_annotations`), module-wide. Fail-first:
  `test_postponed_annotation_call_cannot_justify_the_route` (flagged 0
  before, 1 after); the mirror control
  `test_evaluated_annotation_call_is_real_work` (module without the future
  import) passed before and after, pinning that evaluated annotations still
  justify a handler.
- **Decorator application.** A decorator is applied, not stored: Python
  calls it with the function the moment the def runs, so a lambda
  decorator's body executes exactly once — but the executed-scope walk
  discarded it, condemning as canned a route whose decorator really runs
  `store.write()` (a case the pre-#1858 whole-tree scan caught). Fix:
  `_definition_time_expressions` also yields a lambda decorator's body.
  Fail-first: `test_lambda_decorator_is_applied_so_its_body_runs_once` and
  `test_lambda_decorator_route_is_not_canned`; the stored-lambda cases
  (deferred body) still fail to justify, pinned by the existing lambda
  tests.

The third review note asked to treat ordinary fallthrough as an implicit
constant `None` return. Not taken: a return-less handler with no own-scope
`yield`/`raise` cannot be distinguished from the gate's allowed shapes —
generator responses (`yield`) and raise-only `HTTPException` refusals are
pinned return-less fixtures — so condemning fallthrough would change those
discovery/refusal cases, which the issue forbids. The limit is documented
in the gate's docstring and in `_canned_handlers` instead; no shipped
handler's classification changes either way (gate still OK, 0 canned).

Net test delta for this round: +5 (4 fail-first, 1 control); 51 pass in the
suite after the repair, 46 before it.

## Repair round 2: independent re-verification (no code change)

Re-ran the fail-first proof against the actual merge base rather than the
earlier snapshot, using the final test file against the old scripts:

- vs develop `94781cf6b` (pre-#1858 whole-tree walk): 9 failed, 42 passed —
  every core #1858 case plus both PEP 563 cases (the mode detector and the
  annotation escape do not exist there, so the tests error-fail);
- vs pre-repair head `235f2d3c6`: exactly the 4 repair-round fail-first tests
  fail (2 postponed-annotation, 2 lambda-decorator); the evaluated-annotation
  control passes;
- at this head: 51/51 pass, and the gate reports OK (279 handlers, 15 audited
  routes, 0 canned) with output identical to base and pre-repair, so shipped
  classifications are unchanged.

CI-exact gates re-run locally at `424029fe9`: route-contract gate (ci.yml
"No canned no-op route handlers ship"), `check-vulture-baseline.py packages/*/
src --min-confidence 60 --exclude '*/third_party/*'` (1338 reviewed = 1338
findings), `check-suite-inventory.py` (14/14 suites match),
`check-ratchet-provenance.py`, `check-shipped-surface-truth.py`,
`check-test-duplicates.py`, `check-merge-markers.py`,
`verify-monorepo-layout.sh`, ruff check + format, and the ci.yml one-process
job `pytest tests/ packages/hive-conductor/backend/tests
packages/maistro-design/tests -q --timeout=60` (8351 passed, 97 skipped).
Test count is unchanged by this note: `inventory-delta` above still holds.

## Repair round 3: develop sync for the merge queue (no code change)

The branch stalled in the GitHub merge queue (GH006) because develop had
advanced past the branch's last merge base with the squash of PR #1975
itself (`9a5eb7ba6`). Merging `origin/develop` into the branch conflicted
on exactly the three #1858 surfaces; resolution keeps the branch version,
which is a verified superset — the squash's file blobs are byte-identical
to PR #1975 head `235f2d3c6` (checked via blob ids), an ancestor of the
branch, whose extra delta is only 424029fe9 + 0f2af6741.

Re-proven at the merged head `6627a1795`, including a fresh fail-before
run of the issue's synthetic fixture (uncalled nested `store.write()`
helper, constant return) against a pre-squash develop detector extracted
from `b3662bb37` into a mirrored minimal tree: old detector reports
`0 canned`, exit 0 (the escape); this head's detector reports the route
canned, exit 1 (rejected by the full gate with no disposition).

Gates re-run at `6627a1795`: 51/51 in-process detector tests; backend
contract suite 15/15; shipped-tree gate OK (279 handlers, 15 audited
routes, 0 canned); `check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (1338 reviewed = 1338
findings, base `9a5eb7ba6` = candidate); `check-ratchet-provenance.py`
and `check-shipped-surface-truth.py` (all ratchets evaluate
base `9a5eb7ba6` -> candidate `6627a1795`, no expansion);
`check-suite-inventory.py` 14/14; `check-merge-markers.py`,
`check-cross-package-imports.py`, `check-backlog-consistency.py`,
`verify-monorepo-layout.sh`, ruff check + format, and the ci.yml
one-process job `pytest tests/ packages/hive-conductor/backend/tests
packages/maistro-design/tests -q --timeout=60` (8379 passed, 111
skipped — the merge adds develop's new tests) plus mypy over the CI's
nine `packages/*/src` trees (941 files, no issues). No test added or
removed: `inventory-delta` above still holds.
