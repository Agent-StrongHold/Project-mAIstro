---
inventory-delta:
  packages/hive-conductor/tests/e2e: 0
---
# Issue #358 — native audit export completion

Adds one Playwright case to `pm-workflow.spec.ts`; the registered pytest E2E
suite count is unchanged (23). No inventory baseline or grant changes.

The supplied prior validation stopped at a canceled download in a mocked
component probe. The new case uses the routed production AuditLog component,
a real administrator session and live API (no intercepted audit responses).
It applies action/severity/actor filters, checks retention constants, waits for
a completed browser-native NDJSON download and reads it in the Node runner to
verify every record matches the filters. It asserts the download URL is the
HTTP export route (not a Blob URL) and no export fetch/XHR was issued.

Execution and negative-control evidence are recorded in
`docs/testing/358-73798-repair.md`. Corpus purging is explicitly not claimed;
that policy remains owned by #325.
