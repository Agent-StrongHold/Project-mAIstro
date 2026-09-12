---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---
# fix-codeql-code-scanning-alerts-dd37

Ten hive-conductor backend tests added while clearing the CodeQL code-scanning
alerts; nothing was removed or renamed.

- `tests/test_mcp_defaults_and_manifest.py` (+3, `TestRovoUrlIsMatchedByHost`):
  `is_atlassian_rovo_url` now parses the URL and matches the hostname suffix
  instead of running a substring check on the whole string. The new cases pin
  that an Atlassian host is still matched, that a lookalike host carrying
  "atlassian.net" in the path or query is refused, and that a malformed URL
  (bad IPv6 literal) returns False instead of raising.
- `tests/test_dashboard_request_containment.py` (+7,
  `TestDemoDashboardIdsStayInsideTheDemoDirectory`): the demo-dashboard
  lookup validates the id against a strict allowlist and checks normalized
  containment before reading. Six parametrized traversal/absolute/encoded ids
  are refused with 404, and one well-formed id still resolves.

The two `test_dags_routes.py` assertions that expected a raw exception message
in the run-DAG failure body now expect the sanitized public text; that edit
changes expectations, not the node count.
