---
inventory-delta:
  tests/: +2
---

# Issue #751 repair: git-anchored execution receipts

The prior verification found that an `immutable_execution` receipt was validated only from its own
self-authored JSON fields: a receipt naming a well-formed head SHA that exists nowhere and a
run ID the provider does not retain passed the validator unchanged (run 123456 in the fixture
resolves to HTTP 404).

The validator now anchors every execution receipt to the repository's own git history: the
receipt's `head_sha` must resolve to a commit in the local clone, and the receipt's workflow path
must exist at that commit. Validation fails closed when git is unavailable. The shared fixture
now builds a real mini git repository with a committed workflow and uses its actual head SHA, and
two regression tests cover the new rejections (absent head commit; workflow absent at that
commit).

Provider-side truth (whether GitHub retains the named run and reached the recorded conclusion)
remains outside this deterministic local check and stays deferred to the parent issue's
required-check wiring, per the issue's out-of-bounds list.
