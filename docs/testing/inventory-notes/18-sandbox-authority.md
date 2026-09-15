---
inventory-delta:
  packages/maistro-core/tests/sandbox: +5
---
# #18 — canonical sandbox authority

The canonical selector now registers a socket-less container backend only when
host detection supplies a concrete launcher, while VM-required policies remain
fail-closed when no VM backend is registered. The compatibility
`SandboxConfig.network` field is mechanically rejected in favor of the
policy-owned egress grant. Host mount authorization and descriptor-relative
file transfer tests cover rejected roots and symlink non-following behavior.
