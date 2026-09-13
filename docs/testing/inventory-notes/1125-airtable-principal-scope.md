---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# Issue 1125 — Airtable principal-scoped provider configuration

This note tracks six added conformance cases for the Airtable provider-configuration
ownership fix: two insertion orders, one metadata fallback, two legacy-env mode checks,
and one unavailable-principal-store fail-closed check. The insertion-order cases also
cover client-selected-base rejection for the widget tables route.
