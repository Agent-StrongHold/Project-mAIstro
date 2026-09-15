---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #1190 repair: malformed recognized session credentials

Adds regression coverage proving malformed named session cookies and nested
verifier non-applicability are terminal after the cookie scheme is recognized,
while an unrelated malformed cookie header remains not applicable. Composite
coverage verifies a later provider cannot reinterpret the malformed session.
