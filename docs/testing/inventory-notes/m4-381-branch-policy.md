---
inventory-delta:
  tests/: +12
---
# m4-381 — one branch policy for docs and workflow triggers

#381 single-sourced the topic-branch policy: `.github/branch-protection.json`
gained `topic_branch_policy.prefixes` (feat, bug, fix, idea, doc, chore), the
README stopped recommending the gate-missing `feature/*` spelling, and the
quality/security push triggers now cover every documented prefix instead of
`feat/*` alone — so a push to any branch the docs bless receives the
push-triggered gate set, and PR gates (unfiltered `pull_request`) cover
everything else regardless of prefix.

The +12 node IDs are all in `tests/test_branch_policy.py` (new):

- The policy declares a well-formed non-empty set, and `feature` is not in
  it.
- README, CONTRIBUTING's topic-branch bullet, and WAYS-OF-WORKING's flow
  each name exactly the policy set; README no longer contains `feature/*`.
- quality.yml and security.yml push triggers cover every policy prefix plus
  the protected targets (parametrized, 2 cases).
- ci/quality/security/registry `pull_request` triggers are unfiltered, so
  PR gates run regardless of source-branch prefix (parametrized, 4 cases).
