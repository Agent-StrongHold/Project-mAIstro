---
inventory-delta:
  tests/: +5
---
# claude-655-admission-residency-9e2b

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_measure_merge_latency.py` — 5 node IDs for the residency upgrade
deferred out of #661's review round: residency now clocks from the PR's
earliest `added_to_merge_queue` timeline event instead of the first observed
workflow start. Five distinct test functions, none parametrised.

Two pin `summarize`'s choice of origin: admission wins when present, and an
admission timestamp *later* than the first observed run start is not trusted
— it can only mean the fetched timeline pages missed the admission that
opened this window, and using it would shrink residency below even the
run-start lower bound. One pins the report's fallback disclosure count. Two
cover `collect_admissions`: the earliest admission event wins with other
timeline events ignored, and one unreadable timeline degrades that PR to the
fallback without failing the measurement.

Nothing was removed. One existing render test was rewritten in place to
assert the new residency label ("queue admission -> merged" with the
fallback disclosure) instead of the old lower-bound-only label, and the main
success test gained a `collect_admissions` monkeypatch because `main` now
calls it; neither changes the node count.
