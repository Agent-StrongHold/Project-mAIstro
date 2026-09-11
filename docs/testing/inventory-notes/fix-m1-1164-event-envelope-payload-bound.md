---
inventory-delta:
  packages/maistro-core/tests: +11
---
# fix-m1-1164-event-envelope-payload-bound

Eleven new tests in `test_envelope.py`'s new `TestPayloadStructuralBounds` class
for #1164, which bounds `EventEnvelope.payload`/`provenance` in the envelope's
own `__post_init__`:

- a payload at exactly the 256 KiB byte ceiling is accepted; one byte over is
  rejected;
- a large string value and a large array both count toward the byte ceiling
  (not just an explicitly oversized top-level field);
- `provenance` is bounded the same way as `payload`, independently;
- a payload nested at exactly the 32-level depth ceiling is accepted; one
  level past it is rejected;
- a pathologically deep payload (5000 levels) is rejected cleanly rather than
  exhausting the interpreter's recursion limit, proving the depth check is
  iterative;
- a non-JSON-encodable payload is rejected the same way, before any backend
  ever sees it;
- the bound applies through `EventStore.append` too (both `store` fixture
  parametrizations: memory and SQLite), not just direct construction.

No tests removed or renamed.
