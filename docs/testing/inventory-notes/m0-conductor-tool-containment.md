---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---

# M0 Conductor tool and widget containment

Adds eight focused regressions for #483/#484: ordinary conversational-only chat, dashboard-edit scope blocked before model invocation in both complete/stream paths, conversational-only voice, and stripping generic credentialed-request primitives from top-level and tabbed persisted dashboard widgets, including idempotence/non-mutation behavior.
