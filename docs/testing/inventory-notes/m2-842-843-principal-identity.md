---
inventory-delta:
  packages/maistro-server/tests: +25
  tests/: +26
---

# m2-842-843-principal-identity

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

**+25 `packages/maistro-server/tests`** (27 added, 2 replaced) — the identity
surface of #842 + #843, in two files plus one updated each:

- `test_auth.py`: a new `TestExplicitPrincipalContract` (11 cases) and
  `TestInvalidEntryDescriptions` (3) — legacy plain-key rejection at resolve
  time and over HTTP, the migration prefix preserving access with the same
  secret, the full `principal:secret` pair alias, one-principal rotation
  overlap, two principals never collapsing, the (now-live) `:admin:` role
  form, malformed entries failing closed, revocation by entry removal, and
  secret material never being the principal id nor echoed in gate messages.
  Six pre-existing cases were migrated from plain keys to the
  `principal:secret` contract (they pinned the removed legacy behavior).
- `test_startup.py`: new `TestExplicitPrincipalStartupGate` (5 cases) —
  plain, mixed, and `sk-`-shaped configs refuse to boot with actionable
  guidance that never echoes key material, the gate fires even with
  `require_auth=false`, and prefixed configs pass. Three pre-existing cases
  moved to prefixed fixtures.
- `test_ws.py`: one new case (legacy plain key fails closed on the WS path
  too) and three fixtures migrated to prefixed keys.
- `test_rate_limit.py`: new `TestPrincipalIdentityKeying` (5 cases) plus a
  new different-principals case — one principal across many bearer strings
  shares one bucket (rotation keeps abuse history), invalid bearers never
  mint independent buckets, anonymous traffic cannot evade the pre-auth
  floor by mixing absent/invalid/non-Bearer headers, `X-Forwarded-For`
  cannot rotate the pre-auth identity, and no metric label or response
  surface ever carries credential material. Two of the old
  `TestKeyExtractionPriority` cases — the ones asserting the removed
  raw-header-hash bucketing (different bearer strings minting different
  buckets) — were replaced by the principal-based equivalents.

**+7 `tests/test_secret_env.py`** — a new `TestMigrateApiKeys` class (6 cases) plus a CLI case
for the installer's #843 migration helper: plain entry prefixed in place,
unrelated manual entries untouched, idempotence, a half-migrated state
dropping its stale plain duplicate, an absent secret leaving the file alone,
and a colon-bearing principal refused.

**+19 `tests/api/`** — the root copies of `test_auth.py` and
`test_startup.py` are the static halves of the shipped-image smoke
contract (frozen at the v1 mirror of the server suites). They pinned the
removed legacy behavior verbatim — `user_id == "default"` on a plain key,
plain-key startup fixtures — so they are re-synced to the updated server
suites: +14 principal-contract auth cases and +5 startup-gate cases now
run against the shipped image too, not only in the package suite.

The behavioral change is the contract itself: plain `API_KEYS` entries no
longer authenticate, so the suites that exercised them were migrated to the
`principal:secret` form rather than deleted — the count understates that
every configured-key test in the server package now asserts against the
explicit-principal contract.
