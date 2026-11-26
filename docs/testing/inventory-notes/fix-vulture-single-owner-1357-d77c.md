---
inventory-delta:
  tests/: +12
---

# fix-vulture-single-owner-1357-d77c

Net +12 root-suite tests, two rounds on the same surfaces:

1. +27 root-suite tests covering workflow-level `paths:` filter translation
   and producer untriggerability in `scripts/check-gates-ran.py` and
   `scripts/check-required-checks.py` (#2059).
2. −21 + 6 in the develop-sync round: merging origin/develop brought the
   #2434 incident replay (`test_a_paths_filtered_producer_absent_from_a_green_head_is_pending`)
   and develop's newer `mutation.yml` trigger rows, both of which pin the
   opposite doctrine to this branch's envelope-based untriggerability
   excuse. The reconciled evaluator keeps a paths-filtered producer's
   absence PENDING (#2434: absence is not non-execution; the repair is
   trigger coverage, not evaluator leniency), so the glob-translation class
   and the excuse-pinning tests (21) were removed and a 6-test class now
   pins the reconciled behavior end to end: docs-only envelope → PENDING,
   row present → green, in-scope absence → PENDING, merge-group PR-only
   exclusions, real verdicts still judged. `paths_filters()` and its
   shipped-filter pin remain as a contract check, synced to develop's
   13-entry `mutation.yml` row (#2120/#2371/#2432/#2345/#2450).
