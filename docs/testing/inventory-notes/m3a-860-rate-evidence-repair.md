---
inventory-delta:
  tests/: +5
---

# #860 — preflight evidence cannot sign promotion

Adds five collected cases to `tests/test_soak_promotion_gates.py`:

- Three CLI regressions reject otherwise-passing four-hour evidence when the
  exact-RC artifact check is missing, null, or the actual host-process driver's
  negative artifact verdict. They execute the real evaluator and CLI exit path
  with the expensive load phase replaced; they are not soak evidence.
- Two real production-middleware tests (authenticated and unauthenticated) show
  the same identity exhausting replica 1's allowance while replica 2 retains its
  independent allowance, followed by local 429 + Retry-After on both. No mock
  limiter, alternate identity resolver, scheduler or authorization path is added.

Reconciles the historical H3 shared-store assertion with #842's documented
process-local enforcement and ADR-085's principal identity contract. This does
not meet #860's stronger replica-selection acceptance requirement. Production
rate-limit semantics remain unchanged. The exact-artifact gate is strengthened,
not waived; historical machine evidence is preserved.
