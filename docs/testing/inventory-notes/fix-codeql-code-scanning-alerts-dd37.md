---
inventory-delta:
  packages/hive-conductor/backend/tests: +19
---
# fix-codeql-code-scanning-alerts-dd37

Nineteen hive-conductor backend tests added while clearing the CodeQL
code-scanning alerts; nothing was removed or renamed.

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

Nine more (+9) were added after the diff-coverage floor flagged four files
whose changed lines no test reached. The floor was right to: each of those
lines is the boundary where a failure stops being internal.

- `tests/test_public_failure_text.py` (+8, new file): the four widget paths
  that used to return `str(exc)` to the browser -- Jira query, Airtable
  query, Airtable table listing, dashboard screenshot -- now each assert the
  public text is the exception class plus a fixed sentence, and that the
  seeded message (an internal host, a key path) is absent from the response.
  The screenshot case installs a stub `playwright.async_api` module so it
  lands on the general arm rather than the `ImportError` arm whether or not
  Playwright is on the runner. Two cases cover the RSI run record: a failed
  run stores the exception class in `last_error`, and a cancelled run is
  still recorded as stopped rather than errored. Two more pin the Airtable
  token fingerprint as stable within a process, token-specific, and not
  containing the token.
- `tests/test_dashboard_request_containment.py` (+1): a shipped demo id still
  loads and is sanitized. The six refusal cases already there all pass
  against a guard that refuses everything, so the feature needed its own
  case.
