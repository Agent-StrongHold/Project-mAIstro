---
inventory-delta:
  packages/maistro-turing/backend/tests: +2
---

# Issue #1139 repair - direct actor boundaries and mutation evidence

The Turing boundary inventory now names `TuringActor.handle_memory_event` and
`TuringActor.handle_tool_result` as runtime/service trust boundaries, including
canonical Run/Invocation correlation and fail-closed behavior. Added
actual backend-composition coverage for hostile memory-event content and a
literal source mutation that removes the actor's Warden call; the mutation is
executed in a subprocess and is killed by the security assertion.
