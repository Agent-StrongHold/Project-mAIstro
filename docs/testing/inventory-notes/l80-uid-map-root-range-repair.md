---
inventory-delta:
  packages/maistro-bootstrap/tests: +2
---

# L80 uid-map root-range repair

Issue #80's prior verifier found that the launch classifier treated any
partially non-identity `/proc/self/uid_map` as safe. In particular,
`0 0 1; 1 100000 65536` was admitted even though the one bootstrap `chown`
runs as container uid 0, hence as host root.

The existing parametrized hardening node
`test_uid_map_root_mapping_detection` gains two collected cases: the unsafe
partial uid-0 mapping and a map that does not prove a uid-0 mapping. It now
pins the actual contract: reject when container uid 0 maps to
host uid 0, or when that mapping is malformed/unproven; permit rootless and
userns-remapped maps that map container uid 0 away from host root. The test
uses the production classifier called by `ContainerBuilderSandbox.__enter__`.

Validated with `uv run pytest
packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -q -x`:
26 passed.
