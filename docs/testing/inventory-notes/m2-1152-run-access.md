---
inventory-delta:
  packages/maistro-core/tests: +4
---

# M2-A #1152 Run access

Added four async conformance cases for the canonical Run inspection seam:
foreign Workspace/project ids and child resources fail closed, scoped status
lists require the principal grant, admission records initiating and acting
identities, and delegated acting principals must be owned by the authenticated
principal.
