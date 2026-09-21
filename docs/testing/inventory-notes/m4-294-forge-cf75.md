---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---
# m4-294-forge-cf75 — #294: Agent Forge writes canonical, loadable agent artifacts

The `/v1/agents/forge` route's two old tests pinned the facade #294
retires: a random `forge-xxxxxx` name, empty capabilities, and no
validation, stored as if a pipeline had run. They are replaced by two
classes covering the contract the route now guarantees.

Where the count moved, all in `packages/hive-conductor/backend/tests`:

- Removed 2: `test_forge_agent_normal_mode` and
  `test_forge_agent_custom_strategy` (pinned record-shape only; the
  second posted `"plan-execute"`, a strategy the runtime does not ship,
  and the facade accepted it — the new contract 422s it on purpose).
- Added 10, in `TestForgeCreatesACanonicalArtifact` (valid request →
  scanned, provenance-carrying durable artifact; idempotent
  re-submission; changed request → new artifact; round-trip through the
  execution path incl. reload by id; workspace-scoped spawn-name
  resolution; non-owner 403) and `TestForgeValidatesAndFailsClosed`
  (unknown strategy 422; empty description 422; injected description
  400 with nothing stored; scanner-unavailable 503 fail-closed with
  nothing stored).

Net +8. No other suite moved: the frontend wizard changes carry no
JS/TS test harness in this repo, and the backend route is exercised
through the same `admin_client` HTTP seam as the rest of the file.
