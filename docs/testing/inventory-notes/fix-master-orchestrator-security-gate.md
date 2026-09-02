---
inventory-delta:
  packages/maistro-core/tests: +25
---
# fix-master-orchestrator-security-gate

All twenty-five are in `packages/maistro-core/tests/orchestrator/test_output_security_gate.py`.
Purely additive coverage for the Master Orchestrator output-security gate introduced in
#830: Warden/Sentinel scanning before canonical persistence, fail-closed refusal paths,
sanitized projection of handler output, planner-path gate wiring, and explicit rejection
when callers try to disable or misconfigure the gate. Parametrized cases (untrusted XP
bounds, warden error auditing) account for the five node IDs beyond the twenty named
test functions.
