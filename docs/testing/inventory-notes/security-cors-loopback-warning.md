---
inventory-delta:
  packages/maistro-core/tests: +19
---

# Classify local CORS warning exceptions by parsed authority

Adds 13 deceptive/malformed HTTP origin cases and six exact IPv4/IPv6/localhost
origins. Every configured value remains in the allow-list unchanged. Only the
non-HTTPS warning exemption changes; reverse-proxy HTTP remains accepted.

The full configuration suite passes 156 tests. Original source fails 15 new
regression cases. Ruff check and formatting checks pass.

An isolated whole CORS-file invocation initially hit existing fixture teardown
import-order errors on invalid-origin tests; the broader configuration-suite
run passes without modifying fixtures or test configuration.
