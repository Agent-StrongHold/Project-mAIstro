---
inventory-delta:
  tests/: +8
---
# PR 1398 quality-gate repair

Eight focused regression tests were added while repairing the trust-pipeline
quality gate: message-block extraction/redaction, Agent final-output and
delegated-response Warden blocks, sentinel-repaired tool arguments, dirty tool
results, and the standalone-sanitization bypass used by the Agent-owned
Artificer and React execution paths.

The repair also split the newly introduced high-complexity branches into small
helpers without changing the canonical Agent trust boundary. The radon ratchet
therefore remains unchanged (no baseline or authorization ledger edits).
