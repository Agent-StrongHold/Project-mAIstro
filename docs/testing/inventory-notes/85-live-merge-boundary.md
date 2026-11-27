---
inventory-delta:
  tests/: +56
---

# Issue #85: live merge-boundary verification

Complete the salvaged, truncated read-back tests and add negative checks for
inactive/evaluate rulesets, wrong branch targets, strictness and review-policy
drift, stale default-branch metadata, missing verification credentials,
unreadable classic protection, ambiguous selectors/overlapping rulesets, and
generated live-document drift. A documented divergence must still make live
verification fail: recording evidence is not authorization to weaken policy.

CI-repair round (coverage gate): the read-back machinery's reduction
(`normalize_ruleset`/`normalize_classic`), recording (`fetch_live`,
`write_snapshot`/`load_snapshot`), per-surface drift diagnosis (thread
resolution, protection flags, merge methods, merge queue, classic protection,
uncovered branches), `known_live_drift` accounting, live-region writer
branches, `--refresh-live` credential/error paths, and the `--verify`
end-to-end green path were unexercised — 79% changed-line coverage against a
90% per-file floor. The added tests drive every one of those branches with
synthetic API payloads and monkeypatched transport, so the comparison
machinery is provable without a token or network.

The inventory is collection-based; no baseline or quality grants are changed.
Live GitHub differences require a separately authorized settings decision; the
local implementation is not evidence that those acceptance criteria are met.
