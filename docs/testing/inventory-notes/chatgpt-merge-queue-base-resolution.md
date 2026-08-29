---
inventory-delta:
  tests/: +8
---
# chatgpt-merge-queue-base-resolution

Eight focused root-suite tests pin the single CI base-revision resolver used by pull-request and merge-group gates.

They prove exact pull-request, merge-group, and push base selection; reject cross-event fallback, git's null SHA, malformed SHAs, and unsupported events; and exercise the same `GITHUB_EVENT_NAME` + `GITHUB_EVENT_PATH` path used in GitHub Actions.

No existing test was moved, renamed, parametrized, or deleted, so the root-suite collection change is exactly +8 node IDs.
