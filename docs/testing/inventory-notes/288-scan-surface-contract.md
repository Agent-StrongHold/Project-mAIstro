---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
---
# 288-scan-surface-contract

## What moved

Node-ID deltas (`pytest --collect-only -q`, parametrization expanded):
`packages/hive-conductor/backend/tests/test_scan_contract.py` +6 (three
`TestTheScanSurfaceContract` methods plus a three-way parametrized handler
delegation check), `test_mcp_routes.py` +3 net (one stub-enshrining scan test
removed, four behavioral ones added — clean-with-provenance, malicious
fixture flagged, broken detector 503, hung detector timed-out 503),
`test_agents_routes.py` +6 net (four new test defs, of which the broken- and
hung-scanner ones are parametrized ×2 over both scan routes → 6 nodes).
71 → 86 collected nodes across the three files.

## Why

Issue #288: the `POST /v1/mcp/servers/{server_id}/scan` route was the last
fake-clean scan surface — it answered `{"findings": [], "status": "clean"}`
without running anything, and `test_scan_server_found` asserted exactly that
shape, enshrining the stub. #418 had closed the identical stub on the agent
scan, which proves closing one path does not close its siblings; something has
to enumerate the siblings.

## The tests

- **`test_every_scan_route_runs_a_real_scanner`** — enumerates every `POST
  …/scan` route from the live app (walking FastAPI's lazy
  `_IncludedRouter` wrappers and prepending each `include_context` prefix) and
  requires the set to equal the registered real-scanner handlers, both
  directions. A new scan route fails until its real scanner is registered; a
  registered entry fails if its route vanishes. Note: `routes/projects.py`
  also defines a scan route, but that router is not mounted in `main.py`, so
  it is not a reachable surface and is deliberately absent from the registry.
- **`test_no_production_code_ships_the_fake_clean_literal`** — AST sweep of
  `routes/` and `services/` for the unconditional
  `{"findings": [], "status": "clean"}` dict literal (conditional forms are
  not matched), so a second copy cannot hide behind a new module name.
- **`test_the_scan_handlers_run_the_shared_warden_walk`** — the agent and MCP
  scan handlers must delegate to
  `services.agent_materialization.scan_config`, the same bounded walk the
  write path gates on, not a locally written weaker check.
- **MCP scan behavior** — a known clean fixture reports `clean` with
  provenance (`scanner.name`/`policy_version`, `target`, `scanned_at`,
  `scanned_values`); a known malicious fixture (prompt injection in the
  server description) reports `flagged` naming the field; a broken detector
  answers `503` with no findings list; a missing server stays `404`.
- **Agent scan states** — the same provenance on clean *and* flagged results,
  the by-id route names its saved-agent target, and a broken detector answers
  `503` (unknown) rather than clean on both scan routes. A *hung* detector is
  the same explicit unknown: the routes bound the walk at
  `services.agent_materialization.SCAN_TIMEOUT_SECONDS` via
  `scan_config_bounded` (`asyncio.wait_for`), and the timeout is translated to
  `503` with no findings list — a scan that outlives its budget can neither
  hang the request nor produce a verdict.

## Evidence

From the `packages/hive-conductor` worktree root, at the scan result contract
change (`scan_config` gained `scanner`/`target`/`scanned_at`/`scanned_values`;
routes map scanner failure to `503`):

- `uv run --project ../.. pytest backend/tests/test_agents_routes.py
  backend/tests/test_mcp_routes.py backend/tests/test_scan_contract.py
  backend/tests/test_skills_routes.py backend/tests/test_agent_materialization.py
  backend/tests/test_chat_created_agents.py backend/tests/test_hitl_door.py`
  → 158 passed.
- `uv run --project ../.. pytest backend/tests/test_chat_voice_gates.py
  backend/tests/test_workspace_agent_identity.py` → 65 passed.
- Repo root: `uv run ruff check .` and `uv run ruff format --check .` → clean;
  `python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` → ok after the `+15` delta above
  (was FAIL at the salvage's `+13`, which mis-counted the MCP net and the
  parametrize expansion; the route-level scan-timeout bound and its three
  tests landed after that recount).
