---
inventory-delta:
  tests/: +19
---
# chatgpt-merge-queue-base-resolution

Nineteen focused root-suite tests pin the single CI base-revision resolver used by pull-request and merge-group gates.

They prove exact pull-request, merge-group, and push base selection; reject cross-event fallback, missing/non-object event fields, non-string and malformed SHAs, git's null SHA, unreadable/invalid/non-object event payloads, unsupported events, and missing GitHub event environment. They also exercise both success and fail-closed CLI paths through the same `GITHUB_EVENT_NAME` + `GITHUB_EVENT_PATH` contract used in GitHub Actions.

No existing test was moved, renamed, parametrized, or deleted, so the root-suite collection change is exactly +19 node IDs.
