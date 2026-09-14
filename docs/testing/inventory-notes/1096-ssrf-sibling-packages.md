---
inventory-delta:
  packages/maistro-registry/tests: +2
  tests/: +1
---

# Issue 1096 — sibling-package outbound HTTP guard

The registry linker tests pin the GitHub Contents URL to HTTPS and the
`api.github.com` host while proving owner/repository values are quoted path
segments. They also prove both directory lookups use the guarded-client seam.
The security-inventory gate gains one regression test that keeps the five
sibling-package source roots free of direct `httpx` network calls or private
client constructors.

Existing bootstrap, evolve, RSI, and design tests continue to exercise their
request paths through test transports or patched seam helpers; no test nodes
were added there.
