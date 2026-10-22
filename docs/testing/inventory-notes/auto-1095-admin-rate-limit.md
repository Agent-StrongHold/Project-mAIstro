---
inventory-delta:
  packages/maistro-server/tests: +2
---

# auto-1095-admin-rate-limit

Two rate-limit integration tests for admin-only deployments (API_KEYS empty,
ADMIN_API_KEYS set). Both are **gate-distinguishing**: under the pre-#1095
rule (`if not settings.api_keys` -> every request keyed by the client IP,
limit 2 per bucket) each test's decisive assertion flips, so the tests fail
if `RateLimitMiddleware._extract_key` regresses to the old gate.

- `test_valid_admin_credential_keys_the_principal_bucket` exhausts the
  `principal:ops` bucket, then asserts an invalid bearer from the same client
  still succeeds (untouched `ip:` bucket — old gate: 429, shared bucket) and
  that a second client at a different address sharing the secret is rejected
  (no fresh quota from a new IP — old gate: 200, fresh per-IP bucket).
- `test_invalid_admin_bearer_falls_back_to_client_ip` exhausts the `ip:`
  bucket with invalid credentials, then asserts a valid admin bearer from the
  same client still succeeds (its `principal:` bucket is untouched — old
  gate: 429, shared bucket).

Positive control: with the pre-#1095 gate reinstated in-memory
(`if not settings.api_keys: return _pre_auth_client_key(request)`), both
tests fail (2 failed); with the current gate both pass (2 passed).

Independent re-execution (repair round at head `111ad600a`, repair commit
`e52231a56`, `rate_limit.py` sha256 `6fb9cc62…ad8e95b0`): current gate →
`2 passed, 1 warning in 2.01s`; old gate reinstated in-memory → `2 failed in
2.01s` (both tests); file restored byte-for-byte (sha256 re-verified). The
distinguishing assertions are the same-client invalid bearer after principal
exhaustion and the second client address sharing the secret — exactly the
two scenarios the original review found missing.
