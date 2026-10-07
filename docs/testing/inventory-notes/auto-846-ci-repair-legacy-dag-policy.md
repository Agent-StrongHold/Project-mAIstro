inventory-delta:
  packages/hive-conductor/backend/tests: +0
---
# auto-846-ci-repair-legacy-dag-policy

CI-repair round for #846 at head `583e3ff5ddc1`. Two GitHub Actions runs failed
on that exact head with a single shared root cause:

- `test` (run 36304693882): 2 failed, 2851 passed —
  `packages/hive-conductor/backend/tests/test_legacy_dag_node.py::
  test_legacy_tool_uses_the_canonical_governed_invocation_boundary` and
  `::test_legacy_mutation_is_refused_by_independent_effect_policy`.
- `Coverage gate (publish-set floor + diff coverage)` (run 36304693890): the
  combine step re-runs the hive-conductor suite as a producer and failed on
  the same two tests (2 failed, 2844 passed).

## Root cause

Both tests came from develop (#1454, commit `176043b01`, which is an ancestor
of `origin/develop` 20e6cd4a7). They construct `new_effect_context()` bare and
rely on develop's then-implicit install of the M1 baseline policy. #846
deliberately removed that implicit install: an omitted policy evaluator is an
*unavailable dependency*, so the unnamed context composes
`_unconfigured_policy` and denies (`rule=invocation.unconfigured`,
reason "capability invocation policy unavailable") instead of authorizing.
The merge reconciliation in `7845f478a` updated develop's #1094 tests to the
explicit-composition contract but missed this file — it was outside the
targeted test batch, and both prior local batteries passed 103/166 without it.

The production paths are unaffected and stay fail-closed:

- `maistro/container.py` composition root passes
  `policy_evaluator=binding_scope_policy` explicitly.
- `services/legacy_dag_node.py` falls back to `default_effect_context()`,
  which selects `binding_scope_policy` by name since #846.

Only the two develop-authored tests constructed an unnamed context while
still expecting the M1 baseline's decisions (read-only tool executes;
destructive tool gets `require_approval`).

## Repair

`packages/hive-conductor/backend/tests/test_legacy_dag_node.py` (2 tests,
composition updated, no net count change): both now construct
`new_effect_context(policy_evaluator=binding_scope_policy)` — the exact
composition `default_effect_context()` and the Container perform. The
behavioral pins are unchanged and stronger for #846: the read-only
`web_search` invocation still completes through the canonical governed
boundary with a recorded Invocation, and `jira_write` still returns
`require_approval` with zero provider calls. No production code changed; the
fail-closed default for unnamed contexts is preserved (pinned separately by
`packages/maistro-core/tests/capabilities/test_binding_invocation.py`).

## Validation

- `uv run pytest packages/hive-conductor/backend/tests/test_legacy_dag_node.py -q`
  → 26 passed (was 2 failed, 24 passed).
- Full revalidation battery recorded in the repair commit message.
