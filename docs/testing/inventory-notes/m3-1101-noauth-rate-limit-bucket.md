---
inventory-delta:
  packages/maistro-server/tests: +4
---

# m3-1101-noauth-rate-limit-bucket

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

**+4 `packages/maistro-server/tests`** — #1101 pins the rate-limit bucket
identity of the explicitly unauthenticated development configuration
(`API_KEYS` empty), plus one auth-enabled characterization case:

- `test_rate_limit.py`, new `TestNoAuthDevelopmentBucket` (3 cases) — with
  auth disabled, alternating headerless / arbitrary Bearer / malformed-scheme
  requests from one client stays inside the ONE pre-auth bucket (header text
  can neither mint a second quota nor escape an exhausted one); two
  Bearer-sending development clients at different addresses keep independent
  buckets (before the fix both collapsed into the global `principal:dev`
  bucket); and a verifiable delegation envelope cannot open a
  `delegated-principal:` bucket where no service principal exists (#1101
  stop condition). All three fail against the pre-#1101 middleware.
- `test_rate_limit.py`, `TestPrincipalIdentityKeying` +1 — auth-enabled
  deployments keep principal and pre-auth buckets independent while
  alternating header forms around a valid credential (AC: valid credentials
  bucket by canonical principal, everything else by client identity).
  Passes before and after; it pins the behavior #1101 must not disturb.
- One pre-existing case (`test_valid_credential_keys_the_principal_bucket`)
  now pins `API_KEYS` explicitly: it asserted principal keying but silently
  relied on the ambient environment having no keys, which after #1101 would
  exercise the no-auth `ip:` path instead. No count change.
