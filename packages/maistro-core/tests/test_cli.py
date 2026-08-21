"""`maistro` Typer CLI — thin-client tests using typer.testing.CliRunner.

Covers:
  - `maistro --help` exits 0 and shows help text
  - `maistro approvals list` — prints pending requests
  - `maistro approvals approve <id>` — posts approved=True, prints confirmation
  - `maistro approvals deny <id>` — posts approved=False, prints confirmation
  - `maistro approvals list` when the server returns no pending items
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from maistro.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(handler) -> httpx.Client:
    """Return a real httpx.Client backed by a MockTransport."""
    return httpx.Client(base_url="http://api:8101", transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "approvals" in result.output.lower() or "maistro" in result.output.lower()


def test_approvals_help_exits_zero() -> None:
    result = runner.invoke(app, ["approvals", "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# approvals list
# ---------------------------------------------------------------------------


def test_approvals_list_prints_pending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/capabilities/approvals"
        return httpx.Response(
            200,
            json={
                "pending": [
                    {
                        "request_id": "r1",
                        "action": "restart_stack",
                        "tier": "destructive",
                        "requester": "infra_action",
                    }
                ]
            },
        )

    client = _mock_client(handler)
    ctx_mgr = MagicMock()
    ctx_mgr.__enter__ = MagicMock(return_value=client)
    ctx_mgr.__exit__ = MagicMock(return_value=False)

    with patch("maistro.cli._approvals._client", return_value=ctx_mgr):
        result = runner.invoke(app, ["approvals", "list"])

    assert result.exit_code == 0
    assert "r1" in result.output
    assert "restart_stack" in result.output


def test_approvals_list_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pending": []})

    client = _mock_client(handler)
    ctx_mgr = MagicMock()
    ctx_mgr.__enter__ = MagicMock(return_value=client)
    ctx_mgr.__exit__ = MagicMock(return_value=False)

    with patch("maistro.cli._approvals._client", return_value=ctx_mgr):
        result = runner.invoke(app, ["approvals", "list"])

    assert result.exit_code == 0
    assert "No pending" in result.output


# ---------------------------------------------------------------------------
# approvals approve
# ---------------------------------------------------------------------------


def test_approvals_approve_posts_true() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"resolved": True, "approved": True, "request_id": "r1"})

    client = _mock_client(handler)
    ctx_mgr = MagicMock()
    ctx_mgr.__enter__ = MagicMock(return_value=client)
    ctx_mgr.__exit__ = MagicMock(return_value=False)

    with patch("maistro.cli._approvals._client", return_value=ctx_mgr):
        result = runner.invoke(app, ["approvals", "approve", "r1"])

    assert result.exit_code == 0
    assert "r1" in result.output
    assert seen["path"] == "/v1/capabilities/approvals/r1"
    assert seen["body"] == {"approved": True}


# ---------------------------------------------------------------------------
# approvals deny
# ---------------------------------------------------------------------------


def test_approvals_deny_posts_false() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"resolved": True, "approved": False, "request_id": "r9"})

    client = _mock_client(handler)
    ctx_mgr = MagicMock()
    ctx_mgr.__enter__ = MagicMock(return_value=client)
    ctx_mgr.__exit__ = MagicMock(return_value=False)

    with patch("maistro.cli._approvals._client", return_value=ctx_mgr):
        result = runner.invoke(app, ["approvals", "deny", "r9"])

    assert result.exit_code == 0
    assert seen["body"] == {"approved": False}


# ---------------------------------------------------------------------------
# approve/deny require a request_id argument
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcmd", ["approve", "deny"])
def test_approvals_subcommand_requires_id(subcmd: str) -> None:
    result = runner.invoke(app, ["approvals", subcmd])
    # Typer exits non-zero when a required argument is missing
    assert result.exit_code != 0
