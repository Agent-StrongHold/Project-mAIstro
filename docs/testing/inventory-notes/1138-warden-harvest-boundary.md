---
inventory-delta:
  packages/maistro-rsi/tests: +29
---
# Issue #1138 Warden harvest boundary

Adds collected cases covering recursive RSI harvest admission: ordinary and
structured payload forms, model-call refusal, unavailable-policy fail-closed
behavior, audit correlation/redaction, canonical event persistence, digest
evidence, nested keys, synchronous active-loop refusal, and saved-patch resume
refusal for hostile or unavailable Warden policy.

The repair pass adds `test_non_production_reachability.py` (13 node IDs):
RSI's activation defaults stay pinned to disabled/non-production-reachable
until #552's M5 containment gates. No engine product package may import the
`maistro_rsi` surface; the only product references are the Conductor's two
execution-policy-gated seams; the HTTP run gate stays literally fail-closed
(`IN_PROCESS_ISOLATION_AVAILABLE is False`, and `start_run` resolves
`require_isolation()` before dispatch). Scanner-sensitivity cases prove the
static scans flag every import form (including dynamic `import_module` /
`__import__`) and the activation flips, so a green run is evidence rather
than a vacuous pass.
