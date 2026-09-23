---
inventory-delta:
  packages/maistro-core/tests: +8
---

Adds focused Agent seam coverage for issue #1202: user-input Warden scanning, governed tool-result redaction, Sentinel authorization before raw tool execution, final assistant-output redaction, equivalent final handling across all five shipped strategy families, and the guarantee that persisted assistant content is sanitized. The tests exercise the canonical `Agent.handle` path rather than strategy-specific security helpers.
