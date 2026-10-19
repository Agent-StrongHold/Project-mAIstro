"""CLI-page routes: session bookkeeping plus the #292 command contract.

The web `/cli` page is a limited operational console backed by this router:

- `GET /v1/cli/commands` serves the machine-readable manifest of supported
  commands (the page renders help from it and the compatibility test holds
  the frontend to it).
- `POST /v1/cli/exec` executes one registered command through its backend
  capability (`services/cli_commands.py`), sanitizes the output, appends the
  execution to the CLI session's durable history, and writes an audit entry.
  Anything unregistered is refused with an explicit 404 — the client never
  simulates an answer.
- `GET/POST /v1/cli/sessions` remain the CLI-session bookkeeping the page's
  reconnect/refresh state lives in.

Authorization: like every `/v1/` path, these routes are behind
`AuthMiddleware` — an unauthenticated caller gets 401 before the route runs.
The command set is read-only introspection (the same state the equivalent GET
routes serve), so no elevated scope is required beyond authentication; every
execution is audited regardless. The full contract:
`docs/architecture/CONDUCTOR-CLI-PAGE-CONTRACT.md`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services.cli_commands import cli_registry, normalize_cli_command, sanitize_cli_output
from services.request_principal import optional_actor_id

from routes.audit import log_audit

router = APIRouter(tags=["cli"])

#: Wall-clock budget for one command execution. Handlers are local state
#: reads; a handler that exceeds this answers 504 instead of hanging the
#: page. Read at call time so tests can shorten it.
CLI_EXEC_TIMEOUT_S: float = 10.0

#: Session history is the page's reconnect/refresh state: bounded, durable
#: through the same persistence backend as every other JsonStore, and stored
#: post-sanitization so what is replayed is exactly what was shown.
_HISTORY_LIMIT = 50


@router.get("/sessions", response_model=list[dict[str, Any]])
def list_cli_sessions() -> list[dict[str, Any]]:
    if not stores.cli_sessions:
        stores.cli_sessions["default"] = {"id": "default", "cwd": "/", "history": []}
    return list(stores.cli_sessions.values())


@router.post("/sessions", response_model=dict[str, Any])
def create_cli_session() -> dict[str, Any]:
    sid = str(uuid4())[:8]
    rec = {"id": sid, "cwd": "/", "history": []}
    stores.cli_sessions[sid] = rec
    return rec


class CliExecBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: str = Field(min_length=1, max_length=200)
    session_id: str | None = Field(default=None, max_length=64)


class CliCommandDescriptor(BaseModel):
    name: str
    summary: str


@router.get("/commands", response_model=dict[str, Any])
def list_cli_commands() -> dict[str, Any]:
    """The machine-readable CLI-page contract: the supported command set.

    `GET /v1/cli/commands` is what the page's help output renders and what
    `backend/tests/test_cli_contract.py` holds the frontend to — one registry,
    three consumers.
    """
    return {
        "commands": [
            CliCommandDescriptor(name=c.name, summary=c.summary).model_dump()
            for c in cli_registry().values()
        ]
    }


def _resolve_session(session_id: str | None) -> str:
    if session_id is None:
        # The implicit default must exist whenever it is selected: the store
        # can be nonempty without a `default` record (e.g. POST /sessions
        # minted a random id first), and _append_history would KeyError on it.
        stores.cli_sessions.put_if_absent("default", {"id": "default", "cwd": "/", "history": []})
        return "default"
    if not stores.cli_sessions:
        stores.cli_sessions["default"] = {"id": "default", "cwd": "/", "history": []}
    if session_id not in stores.cli_sessions:
        raise HTTPException(
            status_code=404,
            detail={"error": "unknown_session", "session_id": session_id},
        )
    return session_id


def _append_history(session_id: str, command: str, outcome: str, lines: list[str]) -> None:
    rec = dict(stores.cli_sessions[session_id])
    history = list(rec.get("history", []))
    history.append(
        {
            "command": command,
            "outcome": outcome,
            "lines": lines,
            "at": datetime.now(UTC).isoformat(),
        }
    )
    rec["history"] = history[-_HISTORY_LIMIT:]
    stores.cli_sessions[session_id] = rec


@router.post("/exec", response_model=dict[str, Any])
async def exec_cli_command(body: CliExecBody, request: Request) -> dict[str, Any]:
    """Execute one CLI-page command through its registered backend capability.

    Failure is explicit at the backend, never fabricated in the client:
    unregistered commands answer 404 `unsupported_command`, a handler over
    budget answers 504, and a handler that raises answers 503 — each audited.
    """
    actor = optional_actor_id(request, default="anonymous")
    command = normalize_cli_command(body.command)
    entry = cli_registry().get(command)
    if entry is None:
        # #292: an unsupported command is refused here, audited as a warning,
        # and never answered from the client's imagination.
        log_audit(
            action="cli_exec",
            actor=actor,
            target=command,
            detail={"supported": False, "session_id": body.session_id},
            severity="warning",
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unsupported_command",
                "command": command,
                "hint": "GET /v1/cli/commands lists the supported set",
            },
        )

    try:
        session_id = _resolve_session(body.session_id)
    except HTTPException:
        # #292: a session that vanished (e.g. after a store reset) is still a
        # refusal under the all-executions-and-refusals contract; record it
        # with the acting principal before answering 404 so the frontend's
        # recovery retry cannot leave the original refusal unaudited.
        log_audit(
            action="cli_exec",
            actor=actor,
            target=command,
            detail={
                "supported": True,
                "session_id": body.session_id,
                "outcome": "unknown_session",
            },
            severity="warning",
        )
        raise
    try:
        lines = await asyncio.wait_for(entry.handler(request), timeout=CLI_EXEC_TIMEOUT_S)
    except TimeoutError:
        _append_history(session_id, command, "timeout", [])
        log_audit(
            action="cli_exec",
            actor=actor,
            target=command,
            detail={"supported": True, "session_id": session_id, "outcome": "timeout"},
            severity="warning",
        )
        raise HTTPException(
            status_code=504,
            detail={"error": "cli_command_timeout", "command": command},
        ) from None
    except HTTPException:
        raise
    except Exception:
        log_audit(
            action="cli_exec",
            actor=actor,
            target=command,
            detail={"supported": True, "session_id": session_id, "outcome": "error"},
            severity="warning",
        )
        raise HTTPException(
            status_code=503,
            detail={"error": "backend_unavailable", "command": command},
        ) from None

    safe_lines = sanitize_cli_output([str(line) for line in lines])
    _append_history(session_id, command, "ok", safe_lines)
    log_audit(
        action="cli_exec",
        actor=actor,
        target=command,
        detail={
            "supported": True,
            "session_id": session_id,
            "outcome": "ok",
            "lines": len(safe_lines),
        },
    )
    return {"session": stores.cli_sessions[session_id], "lines": safe_lines, "command": command}
