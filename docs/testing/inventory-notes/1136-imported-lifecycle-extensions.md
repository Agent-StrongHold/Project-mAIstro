---
inventory-delta:
  tests/: +28
---
# Imported lifecycle extensions (#1136)

Twenty-eight cases cover the remaining #1316 review finding: an imported
vocabulary extended with locally visible work states must not disappear below
the ordinary three-state threshold.

The scanner retains an unresolved import as symbolic `<imported-type:...>`
evidence. This names an uninspected type, not an invented status value. A
status-shaped alias or field combining it with an explicit known work state
requires a ledger disposition. Pure imported-type reuse, unrelated fields,
small standalone Literals and Annotated metadata remain outside this rule.
Production source is never imported or executed to discover its types.

Cases cover relative, absolute, renamed and module-qualified imports, Optional,
Union and Annotated wrappers on aliases and fields, lexical shadowing, helper
alias propagation and further field extensions. A real temporary Git-history
fixture proves a candidate cannot self-authorize an imported extension through
its own ledger entry, while genuinely pre-existing source remains distinguishable
as newly visible debt. Existing Enum, scope, wrapper and provenance tests remain
enabled; no test or authorization gate is removed.
