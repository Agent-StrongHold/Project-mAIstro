"""The CLI-page contract tests (#292).

Holds three things together:

1. the backend manifest (`GET /v1/cli/commands`) — the machine-readable
   command set;
2. the execution route (`POST /v1/cli/exec`) — every shipped command really
   executes, unsupported/timeout/backend-failure states answer explicitly,
   output is sanitized, history persists, and every execution is audited;
3. the frontend page — every command literal the page can issue exists in
   the manifest, and the page talks to nothing but the `/v1/cli` contract
   surface (no client-side command simulation survives).
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402

_FRONTEND_CLI_PAGE = (_BACKEND.parent / "frontend" / "src" / "pages" / "CLI.tsx").resolve()

# The shipped command set. If you add a command to the registry, this is the
# line that makes you update the manifest consumers deliberately.
SHIPPED_COMMANDS = ("hctl status", "hctl agents", "hctl health", "hctl sessions", "help")


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clean_cli_state(authed_client: Any):
    _clear(stores.cli_sessions)
    created = []
    yield
    # Remove only the audit rows these tests wrote — audit_log is shared.
    for key, entry in list(stores.audit_log.items()):
        if entry.get("action") == "cli_exec":
            stores.audit_log.pop(key, None)
    _clear(stores.cli_sessions)
    del created


def _manifest(authed_client: Any) -> list[dict[str, str]]:
    r = authed_client.get("/v1/cli/commands")
    assert r.status_code == 200
    return r.json()["commands"]


def _exec(authed_client: Any, command: str, session_id: str | None = None):
    return authed_client.post("/v1/cli/exec", json={"command": command, "session_id": session_id})


def _cli_audit_rows() -> list[dict[str, Any]]:
    return [e for e in stores.audit_log.values() if e.get("action") == "cli_exec"]


def test_manifest_is_the_shipped_command_set(authed_client: Any) -> None:
    commands = _manifest(authed_client)
    assert [c["name"] for c in commands] == list(SHIPPED_COMMANDS)
    assert all(c["summary"].strip() for c in commands)


def test_help_is_rendered_from_the_manifest(authed_client: Any) -> None:
    body = _exec(authed_client, "help").json()
    for command in _manifest(authed_client):
        assert any(command["name"] in line and command["summary"] in line for line in body["lines"])


@pytest.mark.parametrize("command", SHIPPED_COMMANDS)
def test_every_shipped_command_executes_through_the_backend(
    authed_client: Any, command: str
) -> None:
    r = _exec(authed_client, command)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["command"] == command
    assert body["lines"], f"{command} produced no output"
    for line in body["lines"]:
        assert not re.search(r"[\x00-\x1f\x7f-\x9f]", line), (
            f"control characters survived sanitization: {line!r}"
        )
    # The execution landed in the session's durable history.
    sid = body["session"]["id"]
    record = next(s for s in authed_client.get("/v1/cli/sessions").json() if s["id"] == sid)
    assert record["history"][-1]["command"] == command
    assert record["history"][-1]["outcome"] == "ok"


def test_unsupported_command_fails_explicitly_and_is_audited(authed_client: Any) -> None:
    r = _exec(authed_client, "hctl deploy --prod")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "unsupported_command"
    assert detail["command"] == "hctl deploy --prod"
    rows = [e for e in _cli_audit_rows() if e["target"] == "hctl deploy --prod"]
    assert len(rows) == 1
    assert rows[0]["severity"] == "warning"
    assert rows[0]["detail"]["supported"] is False
    # The refusal is not an execution: nothing enters session history.
    assert all(len(s["history"]) == 0 for s in authed_client.get("/v1/cli/sessions").json())


def test_unknown_session_refusal_is_audited(authed_client: Any) -> None:
    r = _exec(authed_client, "hctl status", session_id="gone-after-reset")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "unknown_session"
    rows = [e for e in _cli_audit_rows() if e["detail"].get("outcome") == "unknown_session"]
    assert len(rows) == 1
    assert rows[0]["severity"] == "warning"
    assert rows[0]["actor"]
    assert rows[0]["detail"]["session_id"] == "gone-after-reset"


def test_exec_requires_an_authenticated_principal() -> None:
    from fastapi.testclient import TestClient
    from main import app

    anonymous = TestClient(app)
    assert anonymous.post("/v1/cli/exec", json={"command": "hctl status"}).status_code == 401
    assert anonymous.get("/v1/cli/commands").status_code == 401


def test_handler_timeout_answers_504_and_is_audited(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from services import cli_commands

    async def slow(request: Any) -> list[str]:
        await asyncio.sleep(5)
        return ["never"]

    monkeypatch.setattr(cli_commands, "_status_lines", slow)
    monkeypatch.setattr("routes.cli.CLI_EXEC_TIMEOUT_S", 0.1)
    r = _exec(authed_client, "hctl status")
    assert r.status_code == 504
    assert r.json()["detail"]["error"] == "cli_command_timeout"
    rows = [e for e in _cli_audit_rows() if e["detail"].get("outcome") == "timeout"]
    assert len(rows) == 1
    assert rows[0]["severity"] == "warning"


def test_handler_failure_answers_503_backend_unavailable(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services import cli_commands

    async def broken(request: Any) -> list[str]:
        raise RuntimeError("downstream dependency exploded")

    monkeypatch.setattr(cli_commands, "_agents_lines", broken)
    r = _exec(authed_client, "hctl agents")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "backend_unavailable"
    assert any(e["detail"].get("outcome") == "error" for e in _cli_audit_rows())


def test_output_is_sanitized_before_render_and_persistence(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services import cli_commands

    async def hostile(request: Any) -> list[str]:
        return [
            "\x1b[31mred\u001b[0m status\x07",
            "line\x00with\x1fcontrols\r\nand-newline",
            "x" * 5000,
        ] + ["filler"] * 300

    monkeypatch.setattr(cli_commands, "_status_lines", hostile)
    body = _exec(authed_client, "hctl status").json()
    assert len(body["lines"]) <= 200
    for line in body["lines"]:
        assert "\x1b" not in line and "\x00" not in line and "\x07" not in line
        assert "\r" not in line and "\n" not in line
        assert len(line) <= 1000
    # What is persisted to history is exactly what was rendered.
    history = body["session"]["history"][-1]["lines"]
    assert history == body["lines"]


def test_session_history_persists_for_reconnect_and_refresh(authed_client: Any) -> None:
    first = _exec(authed_client, "hctl status").json()
    sid = first["session"]["id"]
    _exec(authed_client, "hctl agents", session_id=sid)
    sessions = {s["id"]: s for s in authed_client.get("/v1/cli/sessions").json()}
    assert [h["command"] for h in sessions[sid]["history"]] == ["hctl status", "hctl agents"]
    # A page reload reads the same durable record — no client-side state.
    assert sessions[sid]["history"][0]["lines"] == first["lines"]


def test_unknown_session_is_refused_explicitly(authed_client: Any) -> None:
    r = _exec(authed_client, "hctl status", session_id="no-such-session")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "unknown_session"


def test_frontend_command_surface_matches_the_backend_manifest(authed_client: Any) -> None:
    """The machine-readable frontend/backend compatibility test (#292).

    Reads the shipped page source statically: every command-like string
    literal the page can issue must be a manifest command, and every API path
    it calls must live on the `/v1/cli` contract surface. A page that starts
    simulating a command (or calling an endpoint outside the contract) fails
    here, not in production.
    """
    assert _FRONTEND_CLI_PAGE.exists(), f"missing {_FRONTEND_CLI_PAGE}"
    text = _FRONTEND_CLI_PAGE.read_text(encoding="utf-8")
    string_literals = re.findall(r'"([^"\n]*)"|\'([^\'\n]*)\'', text)
    literals = {a or b for a, b in string_literals}

    command_like = sorted(
        lit
        for lit in literals
        if re.fullmatch(r"hctl( [a-z-]+)?|help", lit.strip()) and lit.strip()
    )
    manifest = [c["name"] for c in _manifest(authed_client)]
    unknown = [cmd for cmd in command_like if cmd not in manifest]
    assert unknown == [], f"frontend issues commands the backend does not register: {unknown}"

    api_paths = sorted(lit for lit in literals if lit.startswith("/v1"))
    off_contract = [p for p in api_paths if not p.startswith("/v1/cli")]
    assert off_contract == [], f"CLI page reaches outside the /v1/cli contract: {off_contract}"
    assert api_paths, "compatibility test found no API paths — page rewritten without the contract?"


def test_exec_output_round_trips_json_safely(authed_client: Any) -> None:
    """The health payload is dict-heavy; serialization must never 500."""
    r = _exec(authed_client, "hctl health")
    assert r.status_code == 200
    json.dumps(r.json())  # must be JSON-clean end to end
