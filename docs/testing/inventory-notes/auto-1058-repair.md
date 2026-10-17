---
inventory-delta:
  packages/maistro-core/tests: +4
---
# Issue 1058 repair

Adds typed delegation-evidence validation and consumption coverage plus a
Two-Workspace late/racing settlement regression. Existing deadline tests now
carry the mandatory object-authorization proof. Adds delegated-expiry coverage
proving candidate discovery does not consume one-use settlement evidence,
and requiring typed verified-session evidence for authenticated callers.
