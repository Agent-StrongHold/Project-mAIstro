---
inventory-delta:
  tests/: +5
---
# chatgpt-pr-572-merge-queue-admission

Five focused regression tests were added under `tests/tools/test_enqueue_merge_queue.py` for the trusted merge-queue admission controller.

They pin the controller's security contract rather than GitHub transport details: both exact-head admission signals are required; the newest signal wins if an older green result is followed by a red one; drafts, closed PRs, and non-`develop` targets are refused; the mutation payload is always SHA-bound `squash` + `merge_queue`; and PR parsing takes the current head SHA from GitHub rather than from triggering-event state.

No existing test was moved, renamed, parametrized, or deleted, so the root-suite collection change is exactly +5 node IDs.
