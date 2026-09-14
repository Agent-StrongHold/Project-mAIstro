---
inventory-delta:
  packages/maistro-core/tests: +11
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
Additional demo-session tests cover empty recognized credentials, empty cookie
headers, and missing dependency propagation for the classified provider paths.
Audit coverage also verifies that instance metadata derived from a credential is
not used as the logged scheme label. The classification exceptions now live at
the AuthProvider protocol boundary, so providers do not depend on the composite
implementation to participate in the fail-closed contract.
