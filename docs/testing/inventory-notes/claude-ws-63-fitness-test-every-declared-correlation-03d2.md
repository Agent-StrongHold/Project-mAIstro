---
inventory-delta:
  packages/maistro-core/tests: +11
---
# claude-ws-63-fitness-test-every-declared-correlation-03d2

The eleven new maistro-core node IDs all come from one new file,
`tests/observability/test_correlation_fields_have_producers.py` (#63). It is a
fitness test: every `FIELD_NAMES` correlation field must be bound by a
production `bind_execution_context(...)` call, apart from a reviewed allowlist
that currently holds `invocation_id` and `session_id`. Five node IDs cover that
rule: the producer check, the check that no allowlisted field already has a
producer, that allowlist entries are declared fields, that each entry names its
owner, and that a planted field with no producer fails. The other six pin
the scanner: which files the corpus covers, that every extra root exists, qualified and bare calls, blank
literals and `**` splats not counting, and other calls with the same keywords
being ignored. No existing test moved or was removed.
