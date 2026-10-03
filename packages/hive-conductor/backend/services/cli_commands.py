"""The `/cli` page's command registry — the contract's backend authority (#292).

The Conductor web CLI page is a *limited operational console*, not a shell.
Every command the page offers is registered here, and every registered handler
delegates to the same route-level capability the equivalent API endpoint
serves — `hctl status`/`hctl health` render the payload `/health` computes,
`hctl agents` calls the same `list_agents` projection `GET /v1/agents`
serves, `hctl sessions` reads the backend CLI session store behind
`/v1/cli/sessions`, and `help` is rendered from this registry itself. The
page ships no command whose output the client invents, and anything not in
this registry is refused by `POST /v1/cli/exec` with an explicit
`unsupported_command` failure — never simulated.

The contract this module implements is documented in
`docs/architecture/CONDUCTOR-CLI-PAGE-CONTRACT.md`; the machine-readable
manifest is served by `GET /v1/cli/commands`, and the frontend/backend
compatibility test lives in `backend/tests/test_cli_contract.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import stores
from fastapi import Request

#: A registered command handler receives the request (some capabilities, like
#: the health probe, read `request.app` state) and returns raw output lines.
CliHandler = Callable[[Request], Awaitable[list[str]]]


@dataclass(frozen=True)
class CliCommand:
    """One CLI-page command: its name, help summary, and backend handler."""

    name: str
    summary: str
    handler: CliHandler


#: Command input is matched against this registry by name — no fragment of
#: the user's input is ever interpolated into a shell, query, or template —
#: so sanitizing *input* means normalizing whitespace and bounding length
#: (the route's pydantic model enforces the bound).
def normalize_cli_command(raw: str) -> str:
    """Collapse whitespace so `hctl  status` and `hctl status` are one command."""
    return " ".join(raw.split())


# Output sanitization (#292): handlers read live backend state, so their lines
# are data, not trusted markup. Control characters (which include ANSI escape
# introducers, C1 controls, DEL, CR and LF — handlers return *lines*) are
# stripped, each line is bounded, and the line count is capped so a chatty
# capability cannot flood the terminal, the session history, or the audit
# detail.
_CONTROL_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MAX_OUTPUT_LINES: Final[int] = 200
MAX_OUTPUT_LINE_CHARS: Final[int] = 1000


def sanitize_cli_output(lines: list[str]) -> list[str]:
    """Make handler output safe to render and safe to persist verbatim."""
    safe: list[str] = []
    for raw_line in lines[:MAX_OUTPUT_LINES]:
        cleaned = _CONTROL_CHARS_RE.sub("", str(raw_line))
        safe.append(cleaned[:MAX_OUTPUT_LINE_CHARS])
    return safe


async def _status_lines(request: Request) -> list[str]:
    """`hctl status` — the same operating state the `/health` probe serves."""
    from routes.health import health as health_payload

    payload = health_payload(request)
    agents = [a for a in stores.agents.values() if a.workspace_id is None]
    servers = list(stores.mcp_servers.values())
    connected = sum(1 for s in servers if s.status == "connected")
    lines = [
        f"\u2713 hive-conductor running (uptime {int(payload['uptime_seconds'])}s)",
        f"\u2713 router model: {payload['router_model']}",
        f"\u2713 {len(agents)} agents ready",
        f"\u2713 {connected}/{len(servers)} MCP servers connected",
        "\u2713 vault: {} \u00b7 state: {} \u00b7 reactor: {}".format(
            "enabled" if payload["vault_enabled"] else "disabled",
            "enabled" if payload["state_enabled"] else "disabled",
            "enabled" if payload["reactor_enabled"] else "disabled",
        ),
    ]
    degraded = payload.get("degraded_services") or []
    for d in degraded:
        reason = f" \u2014 {d['reason']}" if d.get("reason") else ""
        lines.append(f"! degraded: {d['service']}{reason}")
    if not degraded:
        lines.append("\u2713 no degraded optional services")
    return lines


async def _health_lines(request: Request) -> list[str]:
    """`hctl health` — the `/health` payload, pretty-printed."""
    from routes.health import health as health_payload

    payload = health_payload(request)
    return [f"  {line}" for line in json.dumps(payload, indent=2, default=str).split("\n")]


async def _agents_lines(request: Request) -> list[str]:
    """`hctl agents` — the exact projection `GET /v1/agents` serves."""
    from routes.agents import list_agents

    agents = await list_agents(request, workspace_id=None)
    if not agents:
        return ["  no agents registered"]
    return [
        f"  {agent.name[:20].ljust(20)} {agent.status.ljust(10)} "
        f"{agent.model[:28].ljust(28)} {agent.tasks_completed} tasks"
        for agent in agents
    ]


async def _sessions_lines(request: Request) -> list[str]:
    """`hctl sessions` — the backend CLI sessions this page's state lives in.

    Deliberately *not* chat sessions: the CLI page's own session records are
    what `GET /v1/cli/sessions` serves, and the page's history persists in
    them — that is the documented relationship (#292).
    """
    from routes.cli import list_cli_sessions

    sessions = list_cli_sessions()
    if not sessions:
        return ["  no CLI sessions"]
    return [
        f"  {str(s.get('id', ''))[:8].ljust(8)} cwd {str(s.get('cwd', '/')).ljust(6)} "
        f"{len(s.get('history', []))} commands"
        for s in sessions
    ]


async def _help_lines(request: Request) -> list[str]:
    """`help` — rendered from the registry, so it can never drift from it."""
    return [
        f"  {command.name.ljust(14)} \u2014 {command.summary}"
        for command in cli_registry().values()
    ]


def cli_registry() -> dict[str, CliCommand]:
    """The supported CLI-page command set, in display order.

    Built per call (handlers resolved from module globals) so tests can patch
    a single handler and drive the route through the real registry path.
    """
    return {
        "hctl status": CliCommand(
            name="hctl status", summary="show system status", handler=_status_lines
        ),
        "hctl agents": CliCommand(name="hctl agents", summary="list agents", handler=_agents_lines),
        "hctl health": CliCommand(
            name="hctl health", summary="health check JSON", handler=_health_lines
        ),
        "hctl sessions": CliCommand(
            name="hctl sessions", summary="list CLI sessions", handler=_sessions_lines
        ),
        "help": CliCommand(name="help", summary="this message", handler=_help_lines),
    }
