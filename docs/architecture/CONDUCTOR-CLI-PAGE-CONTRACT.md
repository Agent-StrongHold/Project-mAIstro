# Conductor CLI page contract (#292)

## Classification: limited operational console

The web `/cli` page in `packages/hive-conductor` is a **limited operational
console** — neither a shell nor a demo panel. It ships a fixed command set;
every command executes server-side through a registered backend capability,
and the page renders what the backend returns. It never simulates an answer,
and it is deliberately *not* a general command surface: there is no shell
parsing, no argument passing, and no path from page input to code execution.
Before #292 the page computed `hctl status` client-side from raw `/health`,
`/v1/agents`, and `/v1/mcp/servers` fetches and hard-coded its own help text;
that client-side simulation is removed.

## Command set (machine-readable)

The authority is the registry in
`packages/hive-conductor/backend/services/cli_commands.py`, served as a
machine-readable manifest by **`GET /v1/cli/commands`**. The shipped set:

| Command         | Summary              | Registered backend capability                                          |
| --------------- | -------------------- | ---------------------------------------------------------------------- |
| `hctl status`   | show system status   | the `/health` probe's payload plus agent/MCP store projections          |
| `hctl agents`   | list agents          | the same `list_agents` projection `GET /v1/agents` serves               |
| `hctl health`   | health check JSON    | the `/health` payload, pretty-printed                                   |
| `hctl sessions` | list CLI sessions    | `GET /v1/cli/sessions` — the CLI session store, not chat sessions       |
| `help`          | this message         | rendered from the registry itself, so it cannot drift from it           |

One registry, three consumers: the exec route, the manifest route, and the
page's help output. The compatibility test
(`packages/hive-conductor/backend/tests/test_cli_contract.py::test_frontend_command_surface_matches_the_backend_manifest`)
reads the shipped `CLI.tsx` statically and fails if the page issues a command
the backend does not register or reaches any path outside `/v1/cli/*`.

## Execution path

**`POST /v1/cli/exec`** with `{command, session_id?}`:

1. `AuthMiddleware` authenticates the caller (401 otherwise) — the same
   boundary as every `/v1/` route.
2. The command is whitespace-normalized and matched against the registry.
   **Unregistered commands answer 404 `unsupported_command`** — the failure
   is explicit and audited (severity `warning`); the client renders it and
   never fabricates output.
3. The registered handler runs under a wall-clock budget
   (`CLI_EXEC_TIMEOUT_S`, 10s). Overruns answer **504**; handler exceptions
   answer **503 `backend_unavailable`**. Both are audited.
4. Output lines are sanitized (control characters stripped, per-line and
   line-count caps) before rendering or persistence.
5. The execution — command, outcome, sanitized output — is appended to the
   CLI session's history (bounded to the last 50 entries) and audited as
   `action="cli_exec"` in the same audit log `/v1/audit` serves.

## Authorization model

Authentication is required and is the boundary: the command set is read-only
introspection of state the equivalent GET routes already serve to any
authenticated principal, so no elevated scope is added and none is bypassed —
`cli_exec` never performs a write an authenticated principal could not make
through the ordinary API. Every execution and every refusal is audited with
the acting principal, so the trail is equivalent to the API's own.

## Relationship to backend CLI sessions

The page's state lives in the backend CLI session store (`stores.cli_sessions`,
served by `GET/POST /v1/cli/sessions`) — the same records `hctl sessions`
lists. History is stored server-side, post-sanitization: reconnecting or
reloading the page restores exactly what was executed and shown, and a page
that finds its session record gone recovers by creating a fresh session and
re-executing for real. The store persists through the same persistence
backend as every other JsonStore (see
[CONDUCTOR-PERSISTENCE-MAP.md](CONDUCTOR-PERSISTENCE-MAP.md)).

## Input/output boundaries

- Input is never interpolated into a shell, query, or template; it is matched
  against the registry by name, bounded to 200 characters by the request
  model, and whitespace-normalized.
- Output is data: control characters (including ANSI escapes) are stripped,
  lines are capped at 1000 characters, and the total is capped at 200 lines
  before rendering, history persistence, or audit.

## Coverage

- Route-level: `packages/hive-conductor/backend/tests/test_cli_contract.py`
  (manifest shape, every command executing, unsupported/timeout/backend
  failure/unauthorized states, sanitization, session persistence, audit
  rows, frontend compatibility).
- E2E: `packages/hive-conductor/frontend/e2e/cli-page.spec.ts` (drives the UI
  from the live manifest; unsupported, unauthorized, timeout, and
  backend-unavailable rendering; refresh-restores-state) and the CLI case in
  `frontend/e2e/degraded-mode.spec.ts` (degraded-status rendering).
- The surface is registered in `quality/shipped-surface-truth.json`
  (`POST /v1/cli/exec`, disposition `canonical`).

## What this page is not

Not a shell, not an agent-commands channel, and not an execution path into
the Goal → Graph → Run → NodeRun → Attempt model — agent work belongs to the
chat/missions/DAG surfaces, not to a status console. New capabilities should
become ordinary API routes first; a CLI entry is a rendering of one, added
deliberately to the registry with coverage in both suites above.
