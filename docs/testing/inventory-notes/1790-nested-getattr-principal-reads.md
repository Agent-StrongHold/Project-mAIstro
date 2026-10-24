---
inventory-delta:
  tests/: +2
---
# 1790 — the principal-identity census sees through defensive nested `getattr`

Issue #1790 (correction 5, the one still open when the lane dispatched) records
that a principal-identity check which "records only 3 violations when the real
count is 31 … is worse than no ratchet, because it certifies a surface it never
measured". The re-land (#1805) fixed the plain `getattr(x.state, "user")`
spelling, but one defensive form remained invisible:

```python
user = getattr(getattr(request, "state", None), "user", None) or {}
```

`_is_state_attr_call` required `args[0]` to be a `.state` attribute, so a
`getattr(x, "state", ...)` call in that position never matched.
`packages/hive-conductor/backend/routes/capabilities.py:290` carried exactly
that spelling — and because AuthMiddleware stopped writing `state.user` when it
migrated to `request.state.principal`, the read resolved to `{}` in production:
the route 401'd every real HTTP approval while the ratchet certified the file
clean.

This change closes both halves:

1. **Scanner** (`scripts/check-principal-identity.py`): a `_is_state_getter`
   helper accepts `x.state` either as a `.state` attribute or as a
   `getattr(x, "state", ...)` call, so the census measures the truth at any
   nesting depth. Tests added under `tests/test_check_principal_identity.py`
   (+2, this note's delta): the defensive user-read is counted, and the same
   spelling for non-principal keys (`request_id`, `org_id`) stays clean.
   The first test was shown to fail against the exact regression it names by
   running it against the pre-fix matcher (git `HEAD`'s script): the nested
   source scanned to zero violations there.
2. **Production** (`packages/hive-conductor/backend/routes/capabilities.py`):
   `resolve_approval` now reads the canonical `request.state.principal` via
   `services.request_principal.request_principal`, the same accessor chat,
   hitl and feedback use. `Principal.has_permission` subsumes the old
   `role == "admin" or principal_has_permission(user, ...)` dance. The two
   `test_chat_voice_gates.py` tests that faked the dict-shaped `state.user`
   now stamp a real `Principal` (admin approve / config-editor 403 semantics
   unchanged); test count there is unchanged, so no delta is recorded for that
   suite (`packages/hive-conductor/backend/tests` re-verified `ok` at its
   recorded inventory).

**No baseline row is added.** The discovered debt is fixed, not tolerated:
`quality/principal-identity-baseline.json` keeps its 4 trusted-base entries and
the ratchet passes as a reduction-free no-op (4 = 4, none new). Adding the
`state_user_access::...capabilities.py` row instead would have needed an
`principal-identity` grant landed at the merge base first (two-merge rule,
#534) — the same "refactor, don't grant" call correction 2 made.
