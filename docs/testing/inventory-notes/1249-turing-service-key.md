---
inventory-delta:
  packages/maistro-turing/backend/tests: +1
---

# Issue #1249 — Turing service key must be explicit

Added a backend startup regression test proving that an unset `TURING_SERVICE_KEY`
causes app construction to fail closed rather than registering a shared hard-coded
service credential.
