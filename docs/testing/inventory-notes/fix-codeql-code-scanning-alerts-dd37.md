---
inventory-delta:
  packages/hive-conductor/backend/tests: +21
  tests/: +7
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

## Review round: the four Codex findings on the PR

Nine more node IDs, all of them pinning a behaviour a reviewer showed was
wrong rather than one that was merely untested.

- `tests/test_codeql_scan_scope.py` (+7, new file): the review found that
  `paths-ignore: "**/test_*.py"` also matched
  `packages/maistro-rsi/src/maistro_rsi/test_inventory.py` -- shipped runtime
  code that launches subprocesses against candidate repositories -- so the
  required Python analysis had silently stopped reading it. An exclusion list
  fails quietly by construction: the job still goes green, it just reports
  less. These walk every shipped tree and assert no entry matches a file that
  is neither a test nor vendored, keep the specific `test_inventory.py`
  regression by name, and check the four real test shapes are still excluded
  so the narrowing did not go too far the other way.
- `packages/hive-conductor/backend/tests/test_rsi_execution_containment.py`
  (+2): `resolve_repo` compared the *requested string* against roots that
  `_authorized_roots` had already resolved, so an `RSI_REPO_ROOTS` entry that
  is itself a symlink refused every legitimate repository beneath the spelling
  the operator configured -- and the obvious way out of that refusal is to
  widen the root. Containment now decides on the resolved path. One case pins
  the symlinked root, one pins that a sibling whose name merely starts with
  the root (`/srv/rsi-evil` against `/srv/rsi`) is still refused.

`packages/maistro-canvas/frontend/server/lulu/tests/test_service_paths.py`
(+7, new file) covers the same class of bug in the Lulu preflight route, whose
containment check ran before `realpath` under a world-writable default root.
It does not appear in the counts above because no CI leg collects
`maistro-canvas/frontend/server` -- that tree's existing `test_preflight.py`
is in the same position. The tests run against the module's own dependencies
and are kept separate from `test_preflight.py`, which needs reportlab.
