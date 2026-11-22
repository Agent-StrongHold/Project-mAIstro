---
inventory-delta:
  packages/maistro-core/tests: +15
---
# fix-m1-1164-event-envelope-payload-bound

Fifteen new tests in `test_envelope.py`'s new `TestPayloadStructuralBounds`
class for #1164, which bounds `EventEnvelope.payload`/`provenance` in the
envelope's own `__post_init__`.

The first eleven, from the initial cut of this change:

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

Four more, added addressing review findings on the same change:

- a lone (unpaired) surrogate in a string field is rejected as
  `EventPayloadTooLarge` rather than letting a raw `UnicodeEncodeError`
  escape the constructor -- `json.dumps` accepts such a string; only the
  later UTF-8 `.encode()` fails, and that encode now happens inside the same
  guarded step;
- a payload nested only through tuples (not dicts/lists) still trips the
  depth ceiling, since `json` serializes a tuple as an array;
- a payload many times over the byte ceiling is still rejected quickly,
  demonstrating the bound check no longer materializes the full encoded
  string before comparing its length;
- a row written before this bound existed (payload already over today's
  ceiling) is still readable through `SqliteEventStore.get`, because row
  reconstruction now goes through `reconstruct_persisted_event`, which skips
  the size/depth ceiling while still checking the invariants that predate
  #1164.

No tests removed or renamed.
