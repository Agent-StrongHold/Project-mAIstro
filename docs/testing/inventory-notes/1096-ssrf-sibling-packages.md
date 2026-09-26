---
inventory-delta:
  packages/maistro-design/tests: +1
  packages/maistro-registry/tests: +2
  packages/maistro-rsi/tests: +1
  tests/: +1
---

# Issue 1096 — sibling-package outbound HTTP guard

The registry linker tests pin the GitHub Contents URL to HTTPS and the
`api.github.com` host while proving owner/repository values are quoted path
segments. They also prove both directory lookups use the guarded-client seam.
The security-inventory gate gains regression tests that keep the five
sibling-package source roots free of direct `httpx` network calls or private
client constructors and exercise alias/method detection.

Existing bootstrap and evolve tests continue to exercise their request paths
through test transports or patched seam helpers. The RSI suite now proves an
explicit private gateway base cannot self-allowlist before the guarded transport
runs. The design suite adds a regression test for the default pooled-client
lifetime; the injected test seam continues to use a private client that is
closed by the provider.

The repair routes Hive Conductor's provider activation and task adapter sync
calls through `maistro.http.sync_client`, eliminating the two repo-wide
production constructor findings. The census now scans production roots
repo-wide (with the documented Docker Unix-socket exception) and follows
imported httpx aliases plus `head`, `options`, and `stream` in regression
fixtures.
