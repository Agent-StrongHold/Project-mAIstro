---
inventory-delta:
  tests/: +39
---
# Definition-time binding snapshots (#1136)

Thirty-nine new collected cases in
`tests/test_check_execution_lifecycle_snapshots.py` complete the binding-order
and lexical-scope guarantees in [ADR-032 section 7](../../adr/ADR-032-contracts-as-acceptance-criteria.md#7-static-lifecycle-discovery-contract-1136).
The prior round's ten scope-review cases and all earlier suites remain intact.

The first scope repair still chased intermediate aliases through a helper's
final binding, evaluated early aliases against the final typing-import map,
and passed class-local imports into nested lexical scopes. The scanner now
captures the environment of each ordinary assignment, including intermediate
bindings and copied typing forms/modules. PEP 695 aliases deliberately retain
their live annotation environment because they are lazy rather than ordinary
assignment snapshots. Nested classes and methods inherit the non-class closure,
not the containing class's imports, typing names, or ordinary attributes.

The cases cover transitive helper snapshots, the reverse false-positive order,
typing-form rebindings, qualified/copy imports, fields extending captured aliases,
class-local import isolation, quoted union operands and named reuse, factored
Literal constants, stage-named aliases/fields, lazy PEP 695 forward references,
and a real temporary Git-history authorization check. String values contribute
only within Literal; runtime strings and Annotated metadata are not type code.

Local source-subset validation: 120 passed, 2 deselected. This includes 39 new
cases, 27 original focused cases, 14 archived binding cases and 40 archived
supplemental stress cases. The archived modules are not extra published tests
or part of this +39 delta. The two full-repository census cases remain enabled
and unchanged in GitHub CI; a source subset is not a full repository run.
Restoring exact prior scanner blob `587b4a77732cd91d96fc6c41902af0180de66705`
makes 33 of the 39 new cases fail, with six controls still passing.

The authorization/provenance evaluator, ledger audit, known-state threshold and
scoped Enum implementation are unchanged. No quality threshold, authorization,
workflow or runtime authority is altered. Full-source census, formatting and
fresh exact-head CI/review remain required before merge.
