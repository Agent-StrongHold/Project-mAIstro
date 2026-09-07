---
inventory-delta:
  tests/: +9
---
# m4-388 — README schedule and embedding claims reconciled with code

#388 reconciled the README's schedule and embedding claims with the code:
the "Schedules — execution" row moved from TODO (nothing executed; "Run now"
only stamped a timestamp) to Partial with the real execution, durability and
convergence facts; the memory bullet stopped claiming the Postgres stores have
no embedding column; the matrix stopped claiming scoped pgvector recall is
live; `maistro.scheduling` left the "no production call path" list.

The +9 node IDs are all in `tests/test_check_retired_guidance.py`, driving the
three new registry entries and the gate's newly governed surfaces:

- The governed set now reaches README.md and docs/architecture/ (the
  user-facing claim surfaces the issue is about).
- Each retired phrasing is reported: "nothing is ever executed", "only stamps
  a timestamp", "learnings/outcome Postgres stores have no embedding column",
  "scoped pgvector recall is live".
- The cited-history forms pass: the #231 stamp-defect record and the #188
  vector-column history are recording, not claiming.
- Every #388 entry declares its replacement and citation markers.

No production code changed; the claims are derived from tests that already
exist (test_scheduler.py's manual-run and canonical-run tests,
tests/migrations/test_memory_embeddings.py, test_memory_entries_embedding_type.py,
test_durable_hybrid.py).
