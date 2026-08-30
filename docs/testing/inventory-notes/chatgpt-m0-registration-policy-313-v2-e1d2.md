---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---
# chatgpt-m0-registration-policy-313-v2-e1d2

`tests/test_registration_policy.py` is a new file: 8 node IDs covering the
fail-closed registration policy (#313) -- default-closed and corrupt-state
behavior, explicit admin open/close, one-time invitation issue/claim/replay,
restoration after a failed validation, and durable-store rehydration across a
fresh process.

No node ID moved or was removed. Merging current `develop` in exposed one
genuine collision this branch's own diff-coverage doesn't touch: `develop`
had independently added an M0-containment placeholder in
`SecurityHeadersMiddleware` that hard-blocked `POST /v1/auth/register`
unconditionally, explicitly commented as a stand-in "until the M2
invitation/admin registration policy lands" -- this PR. That block is now
removed, since `RegistrationPolicyMiddleware` (#313) supersedes it and wraps
`AuthMiddleware` the same way. Three existing tests that had come to depend
on the placeholder's exact 403 message or on registration being reachable at
all were updated in place rather than counted as new node IDs:
`test_public_registration_is_fail_closed` in `test_security_headers.py` now
asserts on `#313`'s own "Registration is closed." detail instead of the
placeholder's message; `test_register_success` /
`test_register_duplicate_username` / `test_register_password_mismatch` in
`test_api.py` needed no code change (their fixture support already existed);
and `conftest.py`'s `_legacy_registration_implementation_tests` fixture,
which used to monkeypatch `SecurityHeadersMiddleware.dispatch` to bypass the
placeholder for a few implementation-focused test modules, now opens and
closes the real `#313` policy through `services.registration_policy` instead
-- the production mechanism an administrator would use, not a test-only
backdoor.
