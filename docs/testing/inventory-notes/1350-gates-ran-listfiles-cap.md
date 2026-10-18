---
inventory-delta:
  tests/: +6
---

# Gates-ran fails closed when the listFiles cap truncates PR scope (#1350)

GitHub's `pulls.listFiles` endpoint exposes at most 3,000 files per pull
request even when fully paginated. The gates-ran changed-files collector
(`.github/workflows/gates-ran.yml`) used to write whatever came back as
`{measured: true}`, so a PR larger than the cap was silently judged on a
partial file set: a leg whose only affected paths fell beyond the cap was
classified out of scope and its skipped specialized check excused — a false
green on partial evidence.

Six node IDs, no removals or renames:

- `tests/test_check_gates_ran.py` (+3): a `truncated: true` envelope is
  refused by `_pull_request_scope` as ambiguity (a `ValueError` that reaches
  the CLI's pending path with the cap named); an explicit `truncated: false`
  leaves a complete measurement intact; and the acceptance case — truncated
  envelope plus every specialized check skipped — yields `PENDING_EXIT`
  (2), not green.
- `tests/test_gates_ran_publisher_contract.py` (+3): the collector step's
  real inline JS is executed against faked `github`/`core` APIs (CommonJS
  harness, since the collector does `require('fs')`) — a 3,000-file response
  is written as `{measured: true, truncated: true}` with an operator
  warning, a short response stays a plain measured envelope, and the
  workflow's `3000` literal is pinned to the evaluator's `LIST_FILES_CAP`
  so the two cannot drift apart.
