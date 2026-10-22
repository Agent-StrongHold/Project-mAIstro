---
inventory-delta:
  tests/: +23
---

# Reusable check discovery implicit string defaults (#1609)

An omitted optional `workflow_call` string input has an implicit empty value.
The discovery parser applies that value only when `type: string` is explicit
and `required` is absent or the boolean `false`. Supplied values and explicit
literal defaults retain their existing precedence. Required, untyped and
non-string declarations do not receive an invented empty-string default;
malformed `required` values are not treated as optional.

Eleven new regressions cover both valid optional forms, empty/whitespace-only
completed names, required inputs, malformed optional flags, and non-string or
missing types. The two positive regressions fail on the previous implementation.
Two additional negative cases previously failed at missing-input resolution;
they now prove final-name validation is retained after the implicit default.
The existing missing-input fixture now explicitly declares `required: true`,
so it tests its stated unresolved-required-input contract rather than relying
on the former optional-input bug. No existing test is removed.

Twelve additional cases cover falsy malformed caller/callee input mappings
and workflow-call trigger configurations.
Only absent/null mappings normalize to an empty mapping; lists, booleans,
numbers and strings are refused before name resolution. All twelve cases fail
against the pre-repair source, which accepted them as absent mappings.

The original conditional, nested, matrix, external/escaping-path, duplicate-name,
PR-base and merge-group regressions remain required. This is parser-only work:
no workflow, required context, queue policy, permission or quality ledger is
changed. The live generated 33-row check table and branch-protection contract
remain unchanged after refresh onto current develop.

Semantics reference:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onworkflow_callinputs
