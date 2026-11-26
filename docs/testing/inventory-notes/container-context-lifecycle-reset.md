---
inventory-delta:
  packages/maistro-core/tests: +5
---
# Container effect-context lifecycle reset

Add five cases in `test_container_effect_context_lifecycle.py`; remove no
tests or assertions. Collection moves from 12,069 to 12,074 core cases.

- Real nested and out-of-order Container teardown preserve the other live
  Container's effect authority, including a repeated close (two cases).
- An explicit `bind_container_effect_context(None)` resets publication and
  the ephemeral fallback (one case).
- Re-publishing a context leaves no stale duplicate and releasing it restores
  the other context (one case).
- A real SQLite connection closed by legacy restart cleanup does not remain
  the default after explicit `cache_clear()`; a fresh Binding write succeeds
  (one case).

The new tests fail three cases on unmodified develop `f5fa4377` and pass all
five with the lifecycle repair. The existing durable-event restart/next-test
sequence also passes. Containers are closed in `finally` on assertion failure.

The change only repairs the publication/cache lifetime introduced by #1819;
it does not change Binding policy, approval storage, quota admission, or
backend selection. This does not establish #1362's remaining acceptance.

Collection was measured with the separate corrections to malformed #1815 and
#1816 inventory-note front matter temporarily applied. The standalone lifecycle
commit excluded them; follow-up integration includes the independently
reviewed #1847 hygiene commit without changing this +5 delta. No inventory
baseline or coverage floor changes.
