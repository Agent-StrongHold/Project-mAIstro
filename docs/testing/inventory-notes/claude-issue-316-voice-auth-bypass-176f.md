---
inventory-delta:
  packages/hive-conductor/backend/tests: +24
  tests/: +24
---
# claude-issue-316-voice-auth-bypass-176f

All 48 are new tests for #316. Nothing was removed, renamed, or moved between
suites. Both numbers are additions to a surface that had none: there were no
tests for `/v1/voice/` at all, which is part of how the prefix stayed in
`_PUBLIC_PREFIXES` for the whole of this repository's history — nothing ever
asked what an anonymous caller got.

## packages/hive-conductor/backend/tests: +24

`tests/test_voice_auth.py` is new.

Four ask the central question directly: an anonymous POST is refused whether or
not voice is configured, a made-up bearer token is refused, and no voice path
remains in any of the three public lists.

Three are about the precise failure of the check being replaced. Its first line
was `if not VOICE_API_KEY: return`, so the shipped default was "no key, no
check, everyone in"; an unset key, a key with no account, and an account with no
key now all refuse rather than admit.

Six cover the credential resolving to a real account: the right key reaches the
route as the satellite's user, the utterance and its room reach the model, an
account that does not exist refuses, a disabled account refuses, and the
principal carries no task-scoped elevation — the key is an identity, not a
permission.

Four assert scope: the device key is refused on `/v1/chat/sessions`,
`/v1/agents`, `/v1/settings` and `/v1/workspaces`, so one device credential is
not a second way into the API.

The rest cover the comparison and the reading. Constant-time is asserted by
observing the call to `secret_equal` rather than by reading the source — #320 is
open precisely because source-inspection tests survive a refactor that keeps the
text and loses the property. Rotation is asserted by changing the configured key
and seeing the old one stop working without reimporting, which the old
module-level constant could not do. Six parametrised cases pin that only a
well-formed `Bearer` header is read.

Putting `/v1/voice/` back into `_PUBLIC_PREFIXES` fails six of these, and the
gate below.

## tests/: +24

`tests/test_check_public_routes.py` covers the registry gate, and is organised
around the ways a bypass could still get through it: a path the middleware makes
public that the registry does not mention; a stale registry entry, which is a
standing approval for whoever next adds that string back; an entry describing a
boundary-safe prefix where the middleware does a bare `startswith`, so the
recorded exemption is narrower than the real one; a missing owner, risk,
disposition or reason; a disposition the gate cannot reason about, which would
otherwise read as "not temporary" and skip the expiry check; and a temporary
exemption that has outlived its own date, which fails and names the issue that
closes it.

The last of those came from the coverage report rather than the plan.
