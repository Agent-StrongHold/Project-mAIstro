---
inventory-delta:
  packages/maistro-core/tests: +26
---
# auto-950 — M9-A2 canonical extension context and lifecycle (#950)

Adds the `packages/maistro-core/tests/extensions/` suite pinning the new
public extension contract (`maistro.extensions`, ADR-104, issue #950). The
26 tests split across two files by what they pin:

- `test_extension_contract_conformance.py` (21) — the interface contracts
  themselves, independent of any one extension implementation: the closed
  public context surface (no store/container/db handles, `__slots__`-pinned),
  declared-only configuration access, service grants requiring declaration
  AND host grant, effect dispatch requiring declaration AND route plus a
  cancellation pre-check, the cancellation view's read-only semantics over
  the canonical task fence (including never swallowing `CancelledError`),
  progress-hook validation, structural lifecycle protocol conformance, and
  extension-attributed lifecycle error wrapping.

- `test_extension_reference_execution.py` (5) — a reference extension
  executing through the canonical `Graph → Run → NodeRun → Attempt` path
  (`AttemptExecutionService` over `PythonExecutionRuntime`): its governed
  effect produces a real canonical `Invocation` row with full correlation,
  provenance and progress land on the canonical event stream with the
  extension identity in the envelope `provenance` field, undeclared effects
  and activation-scope dispatch are refused, and `service.cancel(attempt_id)`
  reaches the extension's cancellation view while the Attempt settles
  CANCELLED with NodeRun/Run terminal.

No existing tests were removed or renamed; the delta is purely additive.
