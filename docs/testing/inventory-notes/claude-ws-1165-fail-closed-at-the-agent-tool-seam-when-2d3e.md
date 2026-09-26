---
inventory-delta:
  packages/maistro-core/tests: +16
---
# claude-ws-1165-fail-closed-at-the-agent-tool-seam-when-2d3e

Fail-closed tool authorization at the Agent seam and in the standalone
ReAct/Artificer strategies (#1165) adds 16 maistro-core node IDs, all in
`tests/agents/test_agent_seam_fail_closed.py`: four `Agent.handle` denial cases
(no Sentinel, no auth, empty table, explicit deny), one explicit-grant
execution case, one `route_request`-without-auth case, and ten standalone
strategy cases (the same five outcomes for ReAct and Artificer).

No test was removed. Two ReAct tests that exercised the no-Sentinel
sanitization fallback through a tool that now never runs were renamed and
narrowed to call that fallback directly
(`test_no_sentinel_fallback_pii_filter_import_error_passes_through_unredacted`,
`test_no_sentinel_fallback_warden_clean_does_not_block`); the count is
unchanged by that swap.
