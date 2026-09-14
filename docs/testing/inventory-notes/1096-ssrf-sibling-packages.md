---
inventory-delta:
  packages/maistro-registry/tests: +2
  packages/maistro-design/tests: +1
  tests/: +1
---

# Issue 1096 — sibling-package outbound HTTP guard

The registry linker tests pin the GitHub Contents URL to HTTPS and the
`api.github.com` host while proving owner/repository values are quoted path
segments. They also prove both directory lookups use the guarded-client seam.
The security-inventory gate gains one regression test that keeps the five
sibling-package source roots free of direct `httpx` network calls or private
client constructors.

Existing bootstrap, evolve, and RSI tests continue to exercise their request
paths through test transports or patched seam helpers. The design suite adds a
regression test for the default pooled-client lifetime; the injected test seam
continues to use a private client that is closed by the provider.
