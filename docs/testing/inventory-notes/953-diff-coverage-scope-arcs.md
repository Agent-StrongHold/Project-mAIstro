---
inventory-delta:
  packages/maistro-core/tests: +3
---
# #953 repair: cover the two changed branch arcs in `ExtensionScope`

The CI coverage gate failed on
`packages/maistro-core/src/maistro/extensions/types.py` — 50% of the 4 branch
arcs the PR changed (partial at lines 412 and 418), under the per-file 80%
branch floor of `scripts/check-diff-coverage.py`.

## What was uncovered

- `ExtensionScope.__post_init__` (line 412): every existing test constructed
  the scope with a non-empty `str` `org_id`, so the `not isinstance(...)` arm
  and the blank-string arm both went unexercised and the `ValueError` at line
  413 never fired.
- `ExtensionScope.describe` (line 418): every existing test used a
  `workspace_id`, so the org-only rendering at line 420 was never produced.

## Tests added (`test_compatibility_trust_authority.py`, `TestAuthority`)

- `test_scope_refuses_a_non_string_org_id` — a non-str `org_id` raises the
  same `ValueError` as a blank one rather than surfacing a downstream
  `AttributeError`.
- `test_scope_refuses_a_blank_org_id` — whitespace-only `org_id` is refused.
- `test_describe_names_the_workspace_only_when_scoped_to_one` — asserts both
  renderings: `org:<id>/workspace:<id>` and bare `org:<id>`.

## Evidence

Reproduced the quality.yml coverage gate locally on the merged tree
(publish-set producers core/canvas/evolve/rsi/bootstrap, plus the
maistro-server and root `scripts` producers, combined as CI combines them):
the publish-set floor holds at 92% (≥ 87), and before the fix
`check-diff-coverage.py` named exactly this file and these two arcs; after the
three tests, arcs 413/420 are recorded and the gate reports
`ok: every measured file this change touches is at or above 90% lines / 80%
branch arcs`.
