---
inventory-delta:
  packages/maistro-core/tests: +3
---

# auto-76-sandbox-mounts

Kata backend now honors authorized writable host mounts and read-only
binds (mirroring Bubblewrap), plus two regression tests; selector.build_config
forwards max_processes. Net +3 collected nodes (2 new tests + 1 previously
unrecorded).
