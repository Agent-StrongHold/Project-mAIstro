---
inventory-delta:
  packages/maistro-core/tests: +7
---

# #1190 composite authentication fail-closed contract

Adds security coverage for the authentication-provider contract: unsupported
credential shapes fall through, recognized but invalid static credentials stop
the chain, provider ordering is deterministic, ambiguous Bearer credentials
remain terminal after recognition, and rejection audit records contain the
scheme without credential material. Provider-specific tests also cover the
new not-applicable versus authentication-error outcomes for static, cookie,
and demo-session providers. JWT coverage also proves that an empty recognized
Bearer credential terminates a composite chain rather than falling through.
