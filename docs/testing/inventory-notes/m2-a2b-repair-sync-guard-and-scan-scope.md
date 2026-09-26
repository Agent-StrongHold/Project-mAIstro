---
inventory-delta:
  packages/maistro-core/tests: +9
  packages/hive-conductor/backend/tests: +3
---

# m2-a2b — repair: sync-guard allow path, screenshot failure paths, scan scope

Repair-phase writer round at head 02bc57a99 (develop base 03c8ba83a). Two
branch-caused gate regressions were found by re-running the CI battery
locally and are repaired here; everything else measured is inherited from
the develop base, not this branch.

What moved and why
------------------

1. **`packages/maistro-core/tests/tools/browser/test_net_guard.py` (+9).**
   Diff coverage showed the `SyncBrowserNetworkGuard` half of
   `tools/browser/guard.py` at 84.7% changed-line coverage: the sync seam
   had only denial-path tests, so its allow/fulfill path, allowed redirect
   hops, redirect bound, configured-origin allowance, WebSocket refusal,
   web-socket-less attach fallback, missing route API fail-closed, and
   abort-delivery-failure branches were all unexecuted. Nine tests drive the
   same controlled sync context through each of those paths, mirroring the
   async guard's matrix — one seam, one policy, both transport protocols
   evidenced.

2. **`packages/hive-conductor/backend/tests/test_browser_network_policy.py`
   (+3).** Diff coverage showed `services/ui_auto_climb.py` at 73.3% changed
   lines: only the blocked-navigation path was exercised. Three tests cover
   the missing Playwright runtime refusal (no unguarded fallback), a launch
   failure taking the finally block down its no-context/no-browser path, and
   the allowed-navigation success payload surviving context/browser close
   failures with the guard provably attached.

3. **`tests/test_check_direct_effects.py` (modified, node count unchanged).**
   The branch made `run_hill_climb.py` governed shipped Python (sync_client
   + `SyncBrowserNetworkGuard`, sites dispositioned under #155 in
   `quality/direct-effect-call-sites.json`) and removed its scan exclusion,
   but left the self-check asserting the old exclusion — the gate failed its
   own test. The test now asserts the intended post-#155 scope: the driver
   is scanned, tests are not.

Local verification executed at this head
----------------------------------------

- `uv run pytest packages/maistro-core/tests -q` → 10220 passed, 673
  skipped, 1 xfailed (one timing flake in
  `test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_
  fallback` under the coverage run passes in isolation; container/postgres
  code is untouched by this branch).
- `uv run pytest packages/hive-conductor/backend/tests -q` → 2719 passed,
  6 skipped.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- Coverage producers re-run for the changed roots (maistro-core,
  hive-conductor/backend, scripts) and
  `scripts/check-diff-coverage.py coverage.xml --base 03c8ba83a` → ok,
  every measured file ≥ 90% lines / 80% branch arcs. The remaining
  "NOT measured" line for `run_hill_climb.py` is the gate's declared
  reporting of a pre-existing producer hole, not a failure; the file is
  outside every MEASURED_ROOT, unchanged by this repair.
- `scripts/check_direct_effects.py` → 50 sites, all dispositioned.
- Real-Chromium route verification (playwright 1.63.0 installed into the
  local venv; cached browsers): `uv run pytest
  packages/maistro-core/tests/tools/browser/test_playwright_transport.py -q`
  → 4 passed. The redirect-to-private case is proven at the actual
  Chromium/Playwright network boundary: the public server 302s into a
  private origin, the guard denies the hop, and the private server
  receives **zero requests**.
- `check-security-inventory.py`, `check-radon-baseline.py`,
  `check-doc-links.py`, `check_enumerations.py`, `check-reachability.py`,
  `check-credential-authority.py`, `check-agent-store-writes.py`,
  `check-contract-markers.py`, `check-image-inventory.py`,
  `check-backlog-consistency.py`, `bump_version.py --check`,
  `check-release-consistency.py`, `vendor_ifeval.py --check`,
  `vendor_bfcl.py --check` → all pass.

Inherited (present at the develop base 03c8ba83a, re-derived, not caused by
this branch — clearing either needs ledger/grant edits that are out of scope
for an ordinary implementation change):

- `scripts/check-vulture-baseline.py` exits 1: 207 "new"
  fastapi-route-handler identities in hive-conductor backend route files
  that are byte-identical between base and head (verified with `git show |
  diff`), against a `quality/vulture-baseline.json` unchanged by the branch.
- `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` fails
  identically at the base worktree (`quality/ac-state.json` unclassified).
