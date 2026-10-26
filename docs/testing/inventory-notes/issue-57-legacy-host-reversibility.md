---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# Issue #57 — legacy host-owned reversibility

Three parameterized regressions execute the legacy adapter's canonical Invocation
path for each shipped tool and assert its recorded tier is the host registry's
`internal`, not a node/config string. A fourth changes the host registration of
`web_search` to `irreversible` and asserts the existing canonical policy refuses
before provider dispatch and emits the correlated approval-required event.

The previous generic-tool success test is replaced (zero collection delta) by
an adversarial raw-dispatcher extension test: a callable in `TOOLS` without a
host schema must not execute. Existing backend-error and LLM/tool dispatch tests
now use registered shipped tools, preserving their behavioral assertions rather
than depending on unrestricted generic execution. The two independent legacy
mutation-policy tests explicitly register their test tool with an internal tier
to prove registry classification cannot weaken the existing mutation floor.

Validation and red/green evidence: `.cursor/context/repair-57-711ef671.md`.
