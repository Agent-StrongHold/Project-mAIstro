---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# Issue 1125 — Airtable principal-scoped provider configuration

This note tracks five added conformance cases for the Airtable provider-configuration
ownership fix: two insertion orders, one metadata fallback, and two legacy-env mode
checks. The insertion-order cases also cover client-selected-base rejection for the
widget tables route.
