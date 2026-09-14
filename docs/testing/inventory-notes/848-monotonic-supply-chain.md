---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/hive-conductor/backend/tests: +3
---
# Issue #848 monotonic supply-chain trust

Adds adversarial coverage for the shared trust boundary: changed skill content
loses host approval, an untrusted registration cannot replace a built-in,
code signatures are rechecked at resolve and code refs cannot be overwritten,
external providers cannot self-promote or replace an installed provider, and
Forge path traversal is refused before the LLM is called. The Conductor tests
cover the explicit MCP approval action and the finite tool allowlist, including
that unapproved server tools are not exposed.
