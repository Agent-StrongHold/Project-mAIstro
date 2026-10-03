---
inventory-delta:
  tests/: +16
---

# #1609 independent-review repairs

Refs #1357 and #160. Sixteen focused cases cover the three review findings and
preservation of safe YAML parsing. Thirteen failed against `c3abb634` before
these repairs; all sixteen pass afterwards, alongside the original 43 cases
(59 passed total under Python 3.13.5 / pytest 9.0.2 / PyYAML 6.0.3).

- Literal input components may be empty; the completed check name must remain
  nonempty. Both explicitly supplied empty suffix and empty default are tested.
- Actions workflow parsing uses a local SafeLoader subclass with YAML 1.2
  boolean resolution. Unquoted input ids on/off/yes/no remain distinct strings;
  true/false remain booleans. Resolver lists are copied rather than mutating
  global PyYAML behavior. Safe constructors still reject Python object tags.
- Duplicate check names are refused across all caller jobs, including a composed
  name colliding with a direct job in the same workflow.

The reviewed changes extend collect(), merge_group_gaps() YAML loading and
_refuse_duplicates(), in addition to the earlier recovered name resolver. The
initial recovery note's unchanged-AST claim described that earlier slice only;
it does not describe these review repairs. No workflow producer, required
context, queue parameter, baseline, permission or service profile is changed.

Boolean semantics reference: https://yaml.org/spec/1.2.2/ext/changes/
This is a safe-loader boolean adjustment, not a claim of implementing every
YAML 1.2 numeric or schema rule.

Published source and regression-test blobs match the locally tested files.
Previous-head CI results are not approval of this new candidate. Full exact-head
CI, existing contract tests, formatting, coverage and independent re-review remain
required. No runtime compute saving is claimed for this prerequisite alone.
