---
inventory-delta:
  packages/maistro-core/tests: +16
---
# #1198 — sandbox host-path boundary

The added cases exercise positive writable-root authorization and denial of
root, home, repository-secret, Docker-socket, and traversal paths. They also
cover symlink targets, descriptor-relative file transfer, a final-open symlink
swap, and the backend's teardown/file-access ownership lock. The conformance
coverage remains in the real bubblewrap backend suite; no fake backend is used
to claim host-boundary evidence.
