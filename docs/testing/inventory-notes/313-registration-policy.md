---
inventory-delta:
  packages/hive-conductor/backend/tests: +29
---
# 313-registration-policy

Close public self-registration after initial setup (#313, M2-A). One new
suite, `tests/test_registration_policy.py`, with 29 collected node IDs:
post-setup refusal (3), the admin policy surface (5), invitations (7, one
parametrized over nothing — the concurrency/expiry/token-shapes cases are
plain tests), first-setup one-shot semantics (3), corrupt-record shapes (5
via `pytest.mark.parametrize` — one `def`, five IDs), restart durability on
real SQLite (1), and the public `/v1/setup/status` leak rule (2).

No suite lost nodes. The M0-era `test_public_registration_is_fail_closed`
in `test_security_headers.py` was rewritten in place for the M2 contract
(route-enforced policy instead of the removed middleware 403) — same node
ID, so no count change from it. Two `test_settings_durability.py` tests
gained a users-store isolation monkeypatch; also no count change, but it is
why those tests no longer clobber the seeded admin when they run first.
