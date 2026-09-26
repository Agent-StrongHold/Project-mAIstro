---
inventory-delta:
  packages/maistro-core/tests: +1
---
# M1-A2 root provisioning and scope wiring

Adds one container reachability test proving ContextAssemblyPolicy and the compatibility `Container.project_store` reference the canonical Project scope store that owns Root Projects.

The existing Workspace conformance failure-path test now covers the shared durable transaction seam: a Root Project provisioning failure rolls back the Workspace rather than relying on a post-commit compensating delete.
