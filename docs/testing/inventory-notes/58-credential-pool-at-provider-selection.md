---
inventory-delta:
  packages/maistro-core/tests: +11
---

# 58 — credential pool/rotation moves to Provider selection

#58 removed the detached credential rotation loop
(`maistro.credentials.rotation.execute_with_pool`) and its protocol module,
and re-homed credential selection on the canonical Invocation path:
`CredentialRouter` (scoped acquisition + outcome-driven cooldown/block) and
`capabilities.credential_routing` (resolver/executor wrappers), with the
router composed into `effect_context`.

Net node-ID delta for `packages/maistro-core/tests`: **+11**.

- **+31** new: `tests/credentials/test_router.py` (scoped acquisition,
  outcome rotation, cooldown mapping — the ADR-063 rotation scenarios
  re-bound to the surface that now owns them).
- **+19** new: `tests/capabilities/test_credential_routing.py` (governed
  Invocation through the routed seams: scope denial, rotation across
  Attempts, exhaustion → `CapabilityUnavailable`, secret containment).
- **+5** new: `TestScopedSelection` plus the unknown-strategy refusal in
  `tests/credentials/test_pool.py` (`select(allowed_key_ids=...)`).
- **−13** removed: the `execute_with_pool`-driven tests in `test_pool.py`
  (detached machinery deleted with this change) and
  `tests/credentials/test_protocols.py` (protocol deleted: nothing
  implemented it; `CredentialRouter` is its scoped successor).

Attribution note: `packages/maistro-core/tests` was already **+26** over its
expected count on `develop` before this branch (9515 collected vs 9489
expected at `5104e1ee`); this note records only this change's +8, per the
one-delta-per-change rule that keeps two test-adding branches from
conflicting. The pre-existing drift is the same class as the +32 recorded in
`276-run-terminal-derivation.md` and needs its own retroactive note.
