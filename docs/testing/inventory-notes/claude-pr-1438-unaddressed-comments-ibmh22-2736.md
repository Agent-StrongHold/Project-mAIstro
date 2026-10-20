---
inventory-delta:
  tests/: +25
---
# claude-pr-1438-unaddressed-comments-ibmh22-2736

Follow-up to the merge-queue batching change (#1438), addressing the review
threads it merged with: the enqueue controller quarantines a head that already
failed inside the queue, the policy gate pins `grouping_strategy=ALLGREEN`, and
the latency measurement attributes candidates rebuilt behind another PR's
failed entry.

Net +25 node IDs in `tests/` (root):

- `tests/tools/test_enqueue_merge_queue.py` +14 — own-tree failure attribution
  through the `pr-N-<parent>` chain (front entry owns its failure; entries
  rebuilt behind a failure are not blamed, including one that raced the
  cancel; an entry behind a green entry owns its failure; a parent outside the
  window reads as the base head; cancelled/running entries are not failures;
  foreign bases and non-queue runs ignored; an unusable timestamp is loud),
  head binding to the earliest `gates-ran` success, the controller
  quarantining a failed head and re-queueing one pushed since, an unreadable
  history refusing every admission, and the paged run listing (2).
- `tests/test_measure_merge_latency.py` +7 — `attribute_rebuilds` chain cases
  (5), the per-PR `rebuilt_behind` count, and the bystander share figure.
- `tests/test_check_required_checks.py` +4 — every non-`ALLGREEN` grouping
  value (parametrized ×4) fails closed.

Measured as collection on `origin/develop` (3442) versus this branch (3467).
