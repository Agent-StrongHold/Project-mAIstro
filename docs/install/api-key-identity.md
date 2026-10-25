# API key identity (`principal:secret`)

Every entry in `API_KEYS` names its **explicit canonical principal**
([#843](https://github.com/Agent-StrongHold/Project-mAIstro/issues/843)):

```dotenv
API_KEYS=["ops:9f2c1d0e…", "alice:7b3a9e11…", "build:admin:5d8f2c40…"]
```

* `principal:secret` — the principal is everything before the first colon,
  the secret is everything after it (secrets containing colons keep working).
* `principal:admin:secret` — additionally grants the `admin` role.

Clients still present only the **bare secret** as the bearer token
(`Authorization: Bearer 9f2c1d0e…`). The principal prefix is server-side
configuration; the full `principal:secret` pair also authenticates.

## Why

Before #843, a plain entry (`API_KEYS=["9f2c1d0e…"]`) authenticated as an
invented `default` user. Distinct credentials therefore shared one identity:
authorization, audit trails, Workspace ownership, rate limiting, and
Invocation provenance could not tell callers apart, and one leaked key was
indistinguishable from another. The server now **refuses to start** while any
plain entry is configured — fail closed, not silently degraded.

## Migration (existing installations)

The secret material does not change, so no client rotates anything: rewrite
each plain entry by prefixing it with the principal that key really belongs
to.

| Before | After |
|---|---|
| `API_KEYS=["9f2c1d0e…"]` | `API_KEYS=["ops:9f2c1d0e…"]` |
| `API_KEYS=["7b3a9e11…","9f2c1d0e…"]` | `API_KEYS=["alice:7b3a9e11…","ops:9f2c1d0e…"]` |

Give **each distinct credential its own principal**. Mapping two unrelated
keys onto the same principal is only correct when they are rotation
overlaps of one credential (see below) — the relationship is then explicit,
durable configuration that an auditor can read straight out of the env file.

`./install.sh` performs this rewrite automatically for the key it owns: on a
re-run over an existing `.env`, its legacy plain entry is migrated to
`conductor:<token>` in place (`scripts/secret_env.py migrate-api-keys`).
Keys you added by hand remain yours to migrate deliberately — the installer
and the server both fail with this document's rewrite rule rather than
guessing an identity for them.

## Rotation

Multiple keys may intentionally belong to one principal — the standard
old-key/new-key rotation overlap:

```dotenv
API_KEYS=["ops:9f2c1d0e…", "ops:c41e8a77…"]
```

Both secrets authenticate as `ops` until the old one is removed. Because
rate limits are keyed to the principal (not to the credential —
[#842](https://github.com/Agent-StrongHold/Project-mAIstro/issues/842)),
rotation does not reset that principal's quota or abuse history.

## Rules the server enforces

* Every entry must parse as `principal:secret` (or `principal:admin:secret`);
  `sk-`-prefixed entries are secret-shaped and rejected as plain.
* Empty principals (`":secret"`) and empty secrets (`"alice:"`) are rejected.
* Key material is never a principal id, log label, metric label, or
  rate-limit bucket id — boot errors describe a bad entry by position and
  defect, never by content.
* Revocation is removing the entry; the secret immediately resolves to
  nothing.
