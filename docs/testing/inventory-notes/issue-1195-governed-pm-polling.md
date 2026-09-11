---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Issue 1195 governed PM polling

Adds four focused tests for the retained Jira and Airtable graph nodes: Binding
scope and credential routing, Invocation provenance and secret containment,
fail-closed missing Binding behavior, completed-effect deduplication, and
per-resume effect keys for Jira wait polling.
