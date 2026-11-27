---
inventory-delta:
  packages/maistro-core/tests: +2
---
# #66 Sentinel final-answer gate must not compress answers as tool results

The Conductor agent's final-answer boundary runs the client-facing answer
through `Sentinel.process_output`. That method also applies the tool-result
token optimizer, which caps output at `MAX_RESULT_LENGTH` (4,000) and appends
`"[... truncated, full result available in trace]"` — correct for tool
results, wrong for the final answer a user asked for. This change adds a
`compress_tool_result` keyword (default `True`, so every existing tool-result
caller keeps its behavior) and passes `compress_tool_result=False` at the
Conductor's final-answer boundary: Warden scanning and PII redaction still
run, only the truncation is skipped.

Two tests in
`packages/maistro-core/tests/security/sentinel/test_process_output_gate.py`
pin both sides: the final-answer boundary preserves the full sanitized
answer with no truncation marker, and the default path still compresses
oversized tool results (regression guard for the flag's default). The
server-side fake records the kwarg so the boundary keeps passing it.
