---
inventory-delta:
  packages/maistro-core/tests: +2
---

# #965 repair — deterministic capacity eviction in WorkingMemoryManager

CI's `coverage (no services)` job (run 37789021930, job 113351120060) failed
with `test_working_memory.py::TestManagerLifecycle::test_eviction_by_capacity_and_ttl[memory]`
asserting `hot('ws-a') is None` against a live projection: with three
projections hydrating microseconds apart, the capacity sweep re-read
`idle_seconds` per candidate inside `max()`, and a scheduler preemption
between two clock reads ranked the newer projection (ws-b) as older, evicting
the wrong LRU entry. The test passes in isolation; the failure is
order/timing-dependent at suite scale.

Fix (`packages/maistro-core/src/maistro/memory/working/projection.py`):
`WorkingMemoryManager` now records a strictly increasing touch generation on
every hydrate, hot-hit, and hot-`observe()` fold (`_mark_touch`), and the
capacity sweep evicts `min` by that generation — insertion-order stable, no
wall-clock reads, so the verdict cannot depend on when the clock was last
sampled. The TTL sweep still uses real idle time; `dispose` /
`release_projections` keep the generation map in sync. Eviction semantics
(least-recently-used first, lossless) are unchanged.

**+2 `packages/maistro-core/tests/memory/test_working_memory.py`**
(one new test × the fixture's two store legs):
`test_capacity_eviction_follows_touch_order_not_clock_reads` — pins the
structural property by forcing the exact contradiction a preempted read
produces (`idle_seconds` monkeypatched so the clock ranks ws-b, hydrated
later, as far more idle than ws-a), then asserting capacity eviction still
removes ws-a; a second leg pins that a hot-`observe()` use refreshes the
generation and saves the workspace on the next capacity pass. Verified to
fail on the pre-fix head (both store legs, same `hot('ws-a') is None`
signature CI reported) and to pass with the fix.

Validation on this head: `uv run pytest packages/maistro-core/tests/memory
packages/maistro-core/tests/testing packages/maistro-core/tests/tools/sandbox
-q` green; ruff check/format clean; `check-suite-inventory.py` green with
this note (drift exactly +1); the full `coverage (no services)` core leg
reproduced locally per `quality.yml` (`coverage run --branch
--source=packages/maistro-core/src/maistro -m pytest
packages/maistro-core/tests --timeout=30 -q`).
