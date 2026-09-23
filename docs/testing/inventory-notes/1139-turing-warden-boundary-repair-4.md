---
inventory-delta:
  packages/maistro-turing/backend/tests: +1/-1
  packages/maistro-core/tests: +1
---

# Issue #1139 repair — composed HTTP mutation evidence and audit invariants

Replaced the isolated runtime mutation harness with a literal mutation of
`backend/security.py` loaded before the actual `backend.main.create_app()`
composition. The subprocess drives the production middleware, auth route, chat
route, and execution plane; removing the middleware `scan_payload` call makes
the hostile request miss its required HTTP refusal assertion, so the security
suite kills the mutation.

The canonical audit record now validates supplied policy-version, SHA-256
content-evidence, and length correlation fields; parameterized core tests pin
those rejections. Canonical security composition also verifies that its
canonical Warden exposes a policy version before it can be injected into an
application root.
