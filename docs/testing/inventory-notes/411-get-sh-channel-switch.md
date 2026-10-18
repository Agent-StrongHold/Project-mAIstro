---
inventory-delta:
  tests/: +12
---
# 411 — get.sh channel switches on an existing single-branch checkout

Twelve tests arrive in a new `tests/test_get_sh_channel_switch.py`, all driving
`get.sh`'s own functions against local `file://` origin fixtures — which,
unlike path clones, honor `--depth 1`, so the shallow semantics under test are
the real ones.

The defect (#411): every one-liner install is a single-branch shallow clone,
whose `remote.origin.fetch` maps only that branch. A bare
`git fetch --depth 1 origin develop` on such a clone lands in FETCH_HEAD alone,
`refs/remotes/origin/develop` is never created, and the `checkout -B develop
origin/develop` after it died with "'origin/develop' is not a commit" — so
re-running the installer with another channel was impossible without deleting
the directory. The fix fetches the requested ref by explicit refspec
(`refs/heads/<REF>:refs/remotes/origin/<REF>`, tags likewise), refuses the
switch while tracked files carry uncommitted changes — the tag path used to
run `checkout --force` and silently discard them — and rolls the checkout back
to its previous position when a switch fails part-way.

Coverage, mapped to the acceptance criteria: main→develop→main→tag→branch
transitions and idempotent re-runs; a tag-pinned clone (the tightest
single-branch refspec) escaping to a branch; shallow state preserved across a
switch; a missing ref and an unreachable remote each leaving the previous
checkout in place; rollback after a mid-switch checkout failure; channel
changes refused on a dirty tree with the user's edits intact (including the
tag-path regression where `--force` would have eaten them); same-branch
updates still honoring git's own protection for local edits; and archive
installs announcing a channel switch, recording the ref in their marker, and
keeping `.env`. Two pre-existing `tests/test_get_sh_recovery.py` cases
continue to pass unchanged.
