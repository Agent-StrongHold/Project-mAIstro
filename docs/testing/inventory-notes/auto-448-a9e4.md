---
inventory-delta:
  packages/maistro-bootstrap/tests: +3
  packages/maistro-core/tests: +3
---
# auto-448-a9e4

Lane L448 (issue #448, M2 initiative) — #1197 repair round at 96381577e and
its follow-up. Every delta is a new test; nothing was removed or duplicated
(cross-suite unique-evidence report: 16702 collected, 16702 unique).

## packages/maistro-bootstrap/tests (+3)

- `tests/test_container_sandbox_output_bound.py` — the read_file/edit_file
  overflow contract (#1197 review, commit 96381577e): a verbatim under-limit
  read, an over-limit `read_file` that raises instead of returning
  "prefix + notice" as content, and `edit_file` refusing an oversized file
  before any write. Authored in that commit but recorded only here; the
  missing note is what this file fixes. The same commit also left the file
  outside `ruff format`'s shape; the reformatting is in this round too.

## packages/maistro-core/tests (+3)

- `tests/sandbox/test_capture.py` — the reap/visibility contracts of the
  bounded capture helpers: `communicate_bounded` must wait past stream EOF so
  a child that closes fds 1/2 and keeps running is not reported from a
  still-`None` `returncode` (`returncode or 0` would read as false success);
  the reap must stay inside the caller's `wait_for` so a fd-closing child
  that never exits surfaces as `TimeoutError` (the executor kill path), not
  a phantom success; and `run_bounded` must return what was drained before
  its join deadline when a descendant inherits the pipes and holds them open
  (incremental `_DrainState` snapshots), instead of losing it with the
  lingering drain thread.
