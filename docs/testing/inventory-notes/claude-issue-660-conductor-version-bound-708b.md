---
inventory-delta:
  tests/: +15
---
# claude-issue-660-conductor-version-bound-708b

All 15 are new, in `tests/test_bump_version.py`; nothing was removed or
renamed. `scripts/bump_version.py` had no test file at all before this — it was
covered only by `quality.yml` running `--check` against the real tree, which
can say the 32 registered sites agree and cannot say anything about the 3 that
were never registered (#660).

Eight of the fifteen are negative cases. That ratio is the point rather than
padding: the change widens an inter-package row to accept a version cap, and
the way that goes wrong is "accepts a cap" quietly becoming "accepts anything",
which only a declaration that must *not* match can detect. The rest cover the
capped and uncapped forms, that a bump moves the lower bound and leaves the cap,
that a drifted declaration still raises rather than dropping out of the checked
set, and that all three hive-conductor sites are registered.
