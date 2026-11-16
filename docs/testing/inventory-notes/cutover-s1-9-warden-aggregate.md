---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
  packages/maistro-core/tests: +12
  tests/: +9
---
# cutover-s1-9-warden-aggregate

Workspace cutover P0.9 ("the Agent scans what the model sees"), tests only.
Each module keeps a strict in-test `KNOWN_GAPS` set: a listed case asserts
today's miss, so a fix fails the test until the entry is deleted.

- `packages/maistro-core/tests` +12 (`security/test_scan_what_the_model_sees.py`):
  Warden blocks the letter-spaced and leetspeak instruction overrides; the two
  halves of a split payload each scan clean alone and are blocked once the
  first turn is passed as `context`; both PII redactors (Sentinel's
  `scan_and_redact` and the log `redact`) remove a Slack token, a bare AWS
  secret access key and a `my_secret = '...'` value. No gaps at this layer.
- `packages/hive-conductor/backend/tests` +6 (`test_chat_gate_scans_model_context.py`):
  what string the Conductor chat gate hands Warden. Gaps (#66): Warden never
  sees the user turns together (one scan per string leaf, no `context`), so
  the split payload reaches the model; and the role value `"assistant"` is
  scanned as content and flagged, so a benign conversation with history is
  refused. Single-turn spaced and leetspeak overrides are refused (not gaps).
- `tests/` +9 (`security/test_sentinel_permission_table_armed.py`): renders
  each shipped Compose stack's engine services and builds Sentinel's table
  through that service's own config path. All seven profile/service pairs
  build an empty table today (gaps, #66); one test fails if a new engine
  service appears in a shipped stack without being listed.
