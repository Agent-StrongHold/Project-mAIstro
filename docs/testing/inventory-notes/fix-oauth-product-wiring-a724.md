---
inventory-delta:
  packages/hive-conductor/backend/tests: +82
  packages/maistro-core/tests: +7
---
# fix-oauth-product-wiring-a724

The core suite gains seven node IDs covering mandatory id-token subjects and
presence, bounded pending OAuth state, invalid state-store capacity, atomic
insert-without-overwrite persistence, and conflict-safe insert timeout/error
paths.

The Hive backend gains 82 node IDs from the OAuth product-wiring matrix:
start/callback/session success, exact anonymous-route boundaries, start
throttling before state allocation, browser/state replay defenses, signature
and provider failures, durable conflict-safe identity links, canonical
login/link/failure audit semantics, callback log secrecy, fixed redirects, typed
non-secret provider configuration, JsonStore conflict-safe inserts, shutdown
error handling, and diff-coverage gap fills for config validation and service
edge cases.

Measurement deliberately ignored the untracked
`test_zz_secreview_scratch.py` reviewer probe file. It is not part of this
branch's intended change and will not exist in CI; banking its transient node
IDs would make the recorded inventory false.
