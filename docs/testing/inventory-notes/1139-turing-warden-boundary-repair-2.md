---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-turing/tests: +8
  packages/maistro-turing/backend/tests: +14
---

# Issue #1139 repair - fail-closed seams and diff-coverage evidence

Second repair pass, after merging develop (ba2f1f077) and reconciling the
execution-plane conflict. The security suites proved the happy and blocked
paths but the per-file diff-coverage gate still showed untested guard seams in
the changed lines. These tests close them with behavior, not coverage-gaming:

- `packages/maistro-core/tests/security/test_composition.py`: the canonical
  security composition (`build_canonical_security_dependencies`) is pinned to
  the canonical `Warden` (with `WARDEN_POLICY_VERSION`) and an `AuditLog` that
  records correlation identifiers and content evidence without content.
- `packages/maistro-turing/backend/tests/test_security.py`: startup refusal
  without canonical Warden or audit log, policy-version refusal for a
  version-less Warden, blocked verdicts when the Warden call raises or the
  verdict cannot be audited, sequence/nested payload walking, middleware
  construction refusal, malformed protected bodies refused with 400, and a
  blocked chat request whose audit sink fails staying refused with 503.
- `packages/maistro-turing/backend/tests/test_chat.py`: direct execution
  blocks hostile input even when the pre-admission audit sink fails, an
  uncomposed execution plane refuses `get_execution_plane`, and the chat
  route answers a request composed without the HTTP middleware verdict.
- `packages/maistro-turing/backend/tests/test_state.py`: the runtime security
  audit callback refuses a Run that has no actor principal, and `get_state`
  refuses before composition.
- `packages/maistro-turing/tests/test_runtime.py`: hostile mapping keys,
  nested mapping values, and sequence elements in memory metadata block the
  write while clean structured metadata stores; chat user input goes through
  the dedicated `scan_user_input` seam and blocked input never reaches the
  provider.
- `packages/maistro-turing/tests/test_bridge.py`: an audit-hook failure turns
  a scanned verdict into blocked (`security_audit_unavailable`), and a working
  hook receives the verdict/content/boundary triple.
