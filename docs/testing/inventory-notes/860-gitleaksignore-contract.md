---
inventory-delta:
  tests/: +8
---
# 860 — `.gitleaksignore` contract test

## What moved

`tests/: +8` — one new file, `tests/test_gitleaksignore_contract.py` (five
test functions, eight collected cases including the parametrized
malformed-fingerprint grammar cases). No other suite moved; no production
code changed, so no coverage-bearing suite is affected.

## Why

CI repair for issue #860: the branch's SAST job
(`SAST (bandit + semgrep + gitleaks)`, a required check) failed because
gitleaks' `generic-api-key` rule re-reports, under every `BASE..HEAD` range
scan that contains it, one field in the round-7 production-stack evidence
pack — an `idempotency_key` the probe client generated to deduplicate its
own POST /tasks retries. It authenticates to nothing, and the file is a
recorded observation, so the fix is a `.gitleaksignore` fingerprint keyed to
the introducing commit, exactly like the 8185c1d0 entry this same lane
recorded earlier.

That mechanism has a failure mode nothing guarded: a fingerprint is
`<40-hex-sha>:<path>:<rule>:<line>`, and gitleaks silently skips an entry it
cannot match. A typo in any component — or line drift after a later merge —
turns the suppression off with no signal at repair time; the gate just goes
red again on some future PR, disconnected from the edit that rotted it. The
new test pins the contract: every entry parses as a fingerprint, paths are
repo-relative, entries are unique, and — for the commits that exist in this
repository — the referenced blob must actually exist at that commit with at
least the flagged line count (`git cat-file -e`/`git show`). Entries whose
commit does not resolve here are the file's documented inherited
pre-snapshot documentation rows and are grammar-checked only.

The lane-repair entry itself is pinned by
`test_contract_covers_the_current_lane_repair`, so the specific SAST
regression this round fixed cannot quietly lose its fingerprint.
