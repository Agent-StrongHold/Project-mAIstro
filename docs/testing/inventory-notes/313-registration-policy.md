---
inventory-delta:
  packages/hive-conductor/backend/tests: +41
---
# 313-registration-policy

Close public self-registration after initial setup (#313, M2-A). One new
suite, `tests/test_registration_policy.py`, with 41 collected node IDs:
post-setup refusal (3), the admin policy surface (5), invitations (7, one
parametrized over nothing — the concurrency/expiry/token-shapes cases are
plain tests), first-setup one-shot semantics (3), corrupt-record shapes (5
via `pytest.mark.parametrize` — one `def`, five IDs), restart durability on
real SQLite (1), and the public `/v1/setup/status` leak rule (2).

Twelve nodes added with the diff-coverage repair of the same PR (the gate
named uncovered refusal paths in `routes/auth.py` and `routes/setup.py`):
register-body token normalization — explicit `null` and whitespace-only
codes read as absent (2); the redemption-race refusal, where the check
passed but the spend failed (1); admin-surface fail-closed shapes — the
route-level 401 for bearer-only callers, and 503s for a policy change or
invitation issue whose write was not observed back (3); setup guard edges
— missing-field 422s parametrized over the three required fields, the
deterministic claim-race 409, and the un-persisted close-out 503 with its
released claim (5); and one-shot setup against the persisted KV record on
real SQLite (1).

No suite lost nodes. The M0-era `test_public_registration_is_fail_closed`
in `test_security_headers.py` was rewritten in place for the M2 contract
(route-enforced policy instead of the removed middleware 403) — same node
ID, so no count change from it. Two `test_settings_durability.py` tests
gained a users-store isolation monkeypatch; also no count change, but it is
why those tests no longer clobber the seeded admin when they run first.
