---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# Issue #57: tool scope belongs to the admitted Run

Two adversarial cases invoke the shipped `governed_web_search` entry point with
real SQLite Container/Run/NodeRun/Attempt records but conflicting ambient
Workspace or Project scope. Both must raise `RunIntegrityError` before the raw
backend or registration of a Binding in the unrelated scope. Correlation strings
cannot replace the immutable scope captured by the canonical Run (ADR-081226-a66b).

One positive control omits ambient scope while retaining the canonical execution
IDs. The completed Invocation must use the persisted Run's Workspace/Project and
correlate to that exact Run/NodeRun/Attempt. Matching nonempty scope is also covered
by the pre-existing production-path test in the same module.

Validation and red/green results: `.cursor/context/repair-57-2c3ee758.md`.
