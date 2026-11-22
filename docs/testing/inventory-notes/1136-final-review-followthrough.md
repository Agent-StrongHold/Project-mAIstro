---
inventory-delta:
  tests/: +38
---
# Final lifecycle discovery review follow-through (#1136 / #1316)

Fifteen binding-order cases and twenty-three scoped-Enum/quoted-annotation
cases extend the existing published regression suite without replacing it.

Binding cases cover imports replacing earlier assignments or definitions,
parameters and local definitions masking imported helpers, reassignment after
import, parameter re-import, and relative `.typing` modules remaining distinct
from the standard library.

Enum cases retain enclosing class/function identities, distinguish siblings and
nested classes, and prove that a trusted nested Enum cannot authorize a new
top-level Literal with the same short name. Quoted-annotation cases cover direct
fields, type-bearing wrapper operands, named reuse, imported extensions, syntax
errors, metadata exclusion, runtime string assignments, and bounded cycles.
Nothing imports or evaluates the source under inspection.

Local source-subset validation passed 105 cases: 27 original focused cases,
40 archived supplemental stress cases, and these 38 new collected cases. Two
full-repository census cases were deselected locally only and remain enabled in
repository CI. The archived stress cases are not published by this change and
are not part of the +38 inventory delta.

Against the preceding hash-verified scanner, these 38 new cases produce 25
failures and 13 passing controls. The provenance, trusted-base lookup,
authorization, audit, main, and work-vocabulary admission functions remain
AST-identical. Enum identity construction is deliberately corrected rather
than described as unchanged. Full exact-head CI and review remain required.
