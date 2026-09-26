---
inventory-delta:
  packages/maistro-core/tests: +6
---
# 74-warden-piimatch-product-path

Round-3 verification of #74 found the Warden ReDoS and PIIMatch evidence lived
at the Sentinel API surface, not on the canonical execution paths the docs
claim. Six tests move that evidence onto the product paths:

- `tests/orchestrator/test_output_security_gate.py` (+3): the real `Warden`
  behind `build_output_security_gate` through `MasterOrchestrator.execute` —
  a catastrophic reject pattern is cut off by the per-search timeout while the
  canonical Run/NodeRun/Attempt projection records only the static refusal; a
  multi-window pathological body proves every reject search receives at most
  `_SCAN_WINDOW_CHARS`; a multi-window benign body completes with the heuristic
  fallback scans likewise windowed.
- `tests/agents/test_base.py` (+3, `TestGovernedExecutorProductPathSecurity`):
  the production governed tool executor — the only effect boundary, because
  `BaseAgent` always sets `security_pipeline=True` — running the real Sentinel,
  real Warden and real PII filter through `Agent.handle`: an AWS key in a tool
  result is masked before it can re-enter model context (and the audit trail
  records `pii_detected`), a Warden refusal surfaces as the static injection
  refusal, and an unavailable PII filter fails closed with the blocking marker
  that the BaseAgent failure predicates and the RCA pipeline record as a failed
  tool call.

The last case is a behavior fix, not just a pin: `BaseAgent._sanitize_tool_result`
previously let an unavailable sanitization dependency propagate and kill the
whole strategy run, bypassing the RCA/Outcome failure semantics the standalone
strategies already shipped. It now returns the same blocking marker
(`Error: [BLOCKED: output sanitization unavailable]`) the strategies return.

SECURITY.md and COMPLIANCE.md product-path evidence sections were rewritten to
cite these executed paths instead of the Sentinel-API tests alone.
