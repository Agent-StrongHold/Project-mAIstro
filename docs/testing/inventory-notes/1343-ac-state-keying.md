---
inventory-delta:
  tests/: +1
---

# AC-state event-invariant base keying

Adds one regression fixture covering the same candidate SHA, grant, and note graph under pull-request and topic-push payloads. It proves both event paths resolve the integration base, expose the same superseder set, and retain the grant instead of letting the candidate's own note manufacture a third independent landing.
