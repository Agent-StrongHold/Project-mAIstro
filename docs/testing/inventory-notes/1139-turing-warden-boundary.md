---
inventory-delta:
  packages/maistro-turing/backend/tests: +6
  packages/maistro-turing/tests: +1
---

# Issue #1139 — Turing inbound Warden boundary

Added actual-backend adversarial coverage for user chat input, nested attacker-controlled
mapping keys, model-derived chat results, and canonical Run-correlated Warden audit evidence.
The chat audit regression also rejects uncorrelated allowed payload entries.
The repair also proves application composition preserves injected canonical security and
state construction refuses an absent canonical security composition. Admission failure now
refuses the request without dispatching an unrecorded chat turn, and runtime verdict audit
requires canonical Run context instead of attributing an unscoped result to Turing.
Added bridge fail-closed and user-input delegation coverage.
