---
inventory-delta:
  packages/hive-conductor/backend/tests: +30
---
# Reject malformed ordinary-DAG Binding selectors (#1085)

Independent review found that Python truthiness and `str()` coercion allowed
malformed selectors to reach valid authority by accident: false, zero, empty
containers and null could act like omission, while integer `123` could select a
legitimate configured string Binding ID `"123"`.

The ordinary model adapter now validates both explicitly provided
`model_binding_id` fields as strings before applying top-level precedence or
empty-string fallback. A malformed top-level or nested value refuses even when
the other field names a valid grant. Omitted fields and empty strings retain the
intentional behavior: top-level nonempty strings take precedence, then nested
nonempty strings, then the admitted helper's unambiguous configured selection.
No value is coerced to a string. Whitespace-only IDs retain their existing
explicit-selection behavior and do not gain an omission fallback.

The 30 additional real-SQLite/Container/final-MockTransport cases include:

- 24 refusal combinations: false, zero, list, object, null and integer values in
  each field, both alone and alongside a usable selector. A legitimate `"123"`
  Binding exists in these fixtures. Assertions require zero HTTP, no Invocation
  against that grant and unchanged persisted Binding definitions.
- Six successful string/precedence/omission combinations, including valid
  string `"123"`, empty top-level fallback, both empty and both omitted.
- The new false-selector, numeric nested-selector and malformed-shadowed-config
  regressions fail against the actual pre-fix committed adapter, reporting
  completed execution rather than refusal. Fixed code passes.

This follow-up changes only the ordinary model selector. The #1954 model-backed
tool selector and sandbox implementation are untouched. The initial ordinary
model leaf's +37 inventory remains separate; total addition is now +67, for
3,449 collected Hive tests. Full local Hive execution and live model gateways
remain prohibited; validation executes only the selected hermetic suites.
