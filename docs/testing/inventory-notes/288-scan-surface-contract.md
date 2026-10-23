---
inventory-delta:
  packages/hive-conductor/backend/tests: +12
---
# 288-scan-surface-contract

## What moved

Node-ID deltas (`pytest --collect-only -q`, parametrization expanded):
`packages/hive-conductor/backend/tests/test_scan_contract.py` +6 (four
`TestTheScanSurfaceContract` methods plus a two-way parametrized handler
delegation check), `test_mcp_routes.py` +0 net (develop's #389 had already
replaced the stub-enshrining scan test with an explicit-unsupported one; the
merge keeps that accepted behaviour and the branch's four real-scan MCP tests
are withdrawn), `test_agents_routes.py` +6 net (four new test defs, of which
the broken- and hung-scanner ones are parametrized ×2 over both scan routes →
6 nodes).

## Why

Issue #288: the agent scan surfaces returned results without provenance, and
`POST /v1/mcp/servers/{server_id}/scan` had been the last fake-clean scan
surface — it answered `{"findings": [], "status": "clean"}` without running
anything, and `test_scan_server_found` asserted exactly that shape, enshrining
the stub. #418 had closed the identical stub on the agent scan, which proves
closing one path does not close its siblings; something has to enumerate the
siblings.

### Develop-sync reconciliation (#389)

`origin/develop` independently closed the MCP stub by refusing explicitly
(`501`, "not implemented in this deployment") rather than wiring a scanner —
an accepted change with its own test. This branch's earlier resolution wired
the shared Warden walk over the stored MCP record. On the develop sync the
accepted `501` behaviour is preserved: #288's acceptance criterion allows an
unsupported surface to return an explicit unknown/error state, and the
contract test now classifies MCP as an explicit-unsupported scan surface
instead of pretending a scanner is wired. The agent and skills surfaces run
real scanners; no surface returns `clean` without a completed analysis.

## The tests

- **`test_every_scan_route_is_registered`** — enumerates every `POST …/scan`
  route from the live app (walking FastAPI's lazy `_IncludedRouter` wrappers
  and prepending each `include_context` prefix) and requires the set to equal
  the registered handlers, both directions. A new scan route fails until its
  handler is registered; a registered entry fails if its route vanishes. Note:
  `routes/projects.py` also defines a scan route, but that router is not
  mounted in `main.py`, so it is not a reachable surface and is deliberately
  absent from the registry (the source sweep still covers its module).
- **`test_no_production_code_ships_the_fake_clean_literal`** — AST sweep of
  `routes/` and `services/` for the unconditional
  `{"findings": [], "status": "clean"}` dict literal (conditional forms are
  not matched), so a second copy cannot hide behind a new module name.
- **`test_the_scan_handlers_run_the_shared_warden_walk`** — the agent scan
  handlers must delegate to `services.agent_materialization.scan_config`, the
  same bounded walk the write path gates on, not a locally written weaker
  check.
- **`test_unsupported_scan_surfaces_refuse_explicitly`** — the MCP surface is
  pinned to `501` (and to no executable `return {... "status": "clean"}`),
  so "unsupported" stays distinct from both "clean" and "failed".
- **Agent scan states** — clean *and* flagged results carry provenance
  (`scanner.name`/`policy_version`/`boundary`, `target`, `scanned_at`,
  `scanned_values`); the by-id route names its saved-agent target; a broken
  detector answers `503` (unknown) rather than clean on both scan routes. A
  *hung* detector is the same explicit unknown: the routes bound the walk at
  `services.agent_materialization.SCAN_TIMEOUT_SECONDS` via
  `scan_config_bounded` (`asyncio.wait_for`), and the timeout is translated to
  `503` with no findings list — a scan that outlives its budget can neither
  hang the request nor produce a verdict.
- **Chat-message payloads** keep develop's per-message context walk and now
  return the same provenance fields, so a message-list scan cannot answer
  clean without saying what ran.

## Evidence

From the `packages/hive-conductor` worktree root after merging
`origin/develop` and resolving the four-file conflict in place:

- `uv run --project ../.. pytest backend/tests/test_scan_contract.py
  backend/tests/test_agents_routes.py backend/tests/test_mcp_routes.py
  backend/tests/test_skills_routes.py backend/tests/test_agent_materialization.py
  backend/tests/test_chat_created_agents.py backend/tests/test_hitl_door.py
  -q` → 162 passed.
- Repo root: `uv run ruff check` on the touched modules → clean;
  `python3 scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` → expected == collected after this
  `+12` delta.
