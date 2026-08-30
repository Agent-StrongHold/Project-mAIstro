---
inventory-delta:
  tests/: +27
---
# chatgpt-merge-queue-base-resolution

Twenty-seven focused root-suite tests pin the CI base-revision and merge-group scoping contracts.

Nineteen prove exact pull-request, merge-group, and push base selection; reject cross-event fallback, missing/non-object event fields, non-string and malformed SHAs, git's null SHA, unreadable/invalid/non-object event payloads, unsupported events, and missing GitHub event environment. They also exercise both success and fail-closed CLI paths through the same `GITHUB_EVENT_NAME` + `GITHUB_EVENT_PATH` contract used in GitHub Actions.

Eight more hold the conservative expensive-leg classifier: missing diff evidence and shared dependency/CI changes force every leg to run; migrations select PostgreSQL; archive changes select MinIO; Hive changes select Hive E2E; package source changes retain wheel/import and image validation; and docs/quality-only changes do not pretend to affect service-specific legs. Docker remains selected for every path copied into any shipped image.

No existing test was moved, renamed, parametrized, or deleted, so the root-suite collection change is exactly +27 node IDs.
