---
inventory-delta:
  packages/maistro-bootstrap/tests: +3
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

## packages/maistro-core/tests (+0, withdrawn 2026-10-19)

This note originally recorded +3 here — the reap/visibility contracts of the
bounded capture helpers (wait past stream EOF before reading `returncode`;
reap inside the caller's `wait_for`; `run_bounded` returning the partial
drain when a descendant holds the pipes). Those tests were written into
`tests/sandbox/test_capture.py`, which the branch then carried as its own
18-test file.

The develop syncs (c9a18d300, a77e2edf9, fe5823181) adopted develop's
per-stream sandbox capture policy, and the merge took develop's
9-test `tests/sandbox/test_capture.py` verbatim — `git diff origin/develop
HEAD -- packages/maistro-core/tests/sandbox/test_capture.py` is empty. The
three contracts survive consolidated inside
`tests/tools/sandbox/test_capture_helpers.py`
(`test_communicate_bounded_reaps_and_bounds_both_streams`,
`test_run_bounded_returns_partial_when_a_descendant_holds_the_pipes`), whose
+18 is counted by `448-tools-capture-drain-helpers.md`. Counting them here
as well double-books three tests that exist once, so the core delta is
withdrawn to 0. Verified against collection on pristine develop (e708451b):
`pytest packages/maistro-core/tests --collect-only -q` → 16503 = develop's
own expected, so no capability gap hides or adds nodes and the branch's true
core increment is exactly what `448-tools-capture-drain-helpers.md` records
(sandbox+tools subtree: 673 → 701).
