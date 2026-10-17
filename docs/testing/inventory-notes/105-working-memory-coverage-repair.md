---
inventory-delta:
  packages/maistro-core/tests: +9
---
# 105 working memory: coverage-gate repair (+9)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

CI-repair round for #105 after the merge-queue coverage gate flagged three
`maistro-core/src/maistro/memory/working/` files under the per-file diff
floor: `render.py` (87.1% of 85 changed lines), `types.py` (88.3% of 77) and
`wiring.py` (50% of 2 changed branch arcs — the `warn=False` opt-out of the
in-memory fallback was never driven). No production code changed — every
flagged line is behavior the feature declares and the tests simply never drove.

`test_working_memory.py` (+9 node IDs: 5 tests, four of them over the suite's
dual-leg `env` parametrization, so both store legs run each one):

- GUIDE budget packing (`render_guide(budget_tokens=...)`): whole index lines
  are dropped, never truncated; a budget nothing fits cannot even open the
  block (an empty GUIDE renders `""`, no header with nothing under it). This
  is the prompt-side twin of the WORKING budget rule the suite already
  asserted, and it guards the degenerate path the epic cares about: a fresh
  Workspace with no log renders neither prompt block.
- `WorkingResult.to_json`/`from_json` round trip: the payload keeps the
  reserved `kind` key explicit, never stores the derived `digest`, survives
  `datetime` isoformat round-tripping, and `from_json` strips a foreign
  `kind` value another writer might have set. This is the serialization
  contract of the reference-addressable record, tested independently of the
  SQLite column store that also carries it.
- `wire_in_memory_working_memory(warn=False)`: the silent twin of the loud
  fallback — a caller who explicitly accepts the lossy in-memory manager gets
  a working manager and no `#301` warning. Pins that the fallback's noise is
  opt-out, not unconditional.
