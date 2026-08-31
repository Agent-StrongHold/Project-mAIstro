---
inventory-delta:
  packages/hive-conductor/backend/tests: +46
  packages/maistro-core/tests: +5
---
# fix-oauth-product-wiring-a724

The core suite gains five node IDs covering mandatory id-token subjects and
presence, bounded pending OAuth state, invalid state-store capacity, and atomic
insert-without-overwrite persistence.

The Hive backend gains 46 node IDs from the OAuth product-wiring matrix:
start/callback/session success, exact anonymous-route boundaries, start
throttling before state allocation, browser/state replay defenses, signature
and provider failures, durable conflict-safe identity links, canonical
login/link/failure audit semantics, callback log secrecy, fixed redirects, and
typed non-secret provider configuration.

Measurement deliberately ignored the untracked
`test_zz_secreview_scratch.py` reviewer probe file. It is not part of this
branch's intended change and will not exist in CI; banking its transient node
IDs would make the recorded inventory false.
