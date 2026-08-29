---
inventory-delta:
  packages/maistro-server/tests: +18
---
# 523-workspace-api

Adds 18 maistro-server tests for the canonical Workspace identity and membership API: authenticated create/list/get, membership-scoped visibility, owner-only administration, last-owner refusal, identity updates/deletion, whitespace-only identity rejection at the HTTP boundary, production route mounts, and fail-closed behavior when no canonical Workspace store is configured.
