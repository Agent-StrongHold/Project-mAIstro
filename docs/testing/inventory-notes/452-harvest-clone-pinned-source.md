---
inventory-delta:
  packages/maistro-rsi/tests: +5
---
# 452-harvest-clone-pinned-source

## What moved and why

CI's diff-coverage gate failed on the #452 cloud-harvest clone:
`packages/maistro-rsi/src/maistro_rsi/__main__.py` measured 87.5% of its
changed lines (floor 90%) with exactly three uncovered lines — the
digest-refusal `raise` and the two checkout calls that materialize the pinned
object. The cause was a test gap, not a coverage accident:
`test_an_allowed_clone_url_resolves_then_fetches_a_digest_under_pins` in
`test_harvest_entry_point.py` stubs `subprocess.run` and raises at the fetch,
so everything after it (detach checkout, branch checkout) and the refusal
raise could never execute.

`packages/maistro-rsi/tests/test_harvest_clone_source.py` (new, 5 node IDs)
runs real git for those steps against a local `file://` origin:

- happy path: the workspace's branch and HEAD land on the resolved digest and
  the work tree is materialized (covers the two checkouts);
- the `core.autocrlf=false` pin persists into the clone;
- the remote is exactly the approved URL;
- refusal: a base ref that matches nothing, and an unreachable remote, both
  raise before `git init` creates a workspace (covers the digest guard).

+5 on `packages/maistro-rsi/tests`; no other suite touched.
