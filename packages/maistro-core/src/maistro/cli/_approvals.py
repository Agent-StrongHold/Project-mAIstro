"""`maistro approvals` subcommand — HITL approval inbox.

Moved from the original argparse cli.py. Preserves exact behavior.
"""

from __future__ import annotations

import os

import httpx
from rich.console import Console
from typer import Typer

from maistro.http import sync_client
from maistro.security.outbound import configure_outbound_policy

_DEFAULT_BASE = "http://127.0.0.1:8101"

console = Console()
app = Typer(help="Manage the HITL approval inbox.")


def _client() -> httpx.Client:
    base = os.environ.get("MAISTRO_API_URL", _DEFAULT_BASE)
    token = os.environ.get("MAISTRO_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    # The conductor base is operator configuration (env var or the default), so
    # it is registered as its exact origin before the client is built — the
    # same allowance `HomeAssistantIntegration` and `OAuthService` make for a
    # URL that settings do not carry. Everything else this client could be
    # asked to reach stays behind the guard `sync_client` applies (#67).
    configure_outbound_policy(base)
    return sync_client(base_url=base, headers=headers, timeout=10.0)


@app.command("list")
def approvals_list() -> None:
    """List pending approval requests."""
    with _client() as client:
        resp = client.get("/v1/capabilities/approvals")
        resp.raise_for_status()
        pending = resp.json()["pending"]

    if not pending:
        console.print("No pending approvals.")
        return
    for req in pending:
        console.print(
            f"{req.get('request_id', '?')}  {req.get('action', '?')}  "
            f"[{req.get('tier', '?')}]  by {req.get('requester', '?')}"
        )


@app.command("approve")
def approvals_approve(request_id: str) -> None:
    """Approve a pending request."""
    with _client() as client:
        resp = client.post(f"/v1/capabilities/approvals/{request_id}", json={"approved": True})
        resp.raise_for_status()
        out = resp.json()
    console.print(f"Request {out.get('request_id', request_id)} approved.")


@app.command("deny")
def approvals_deny(request_id: str) -> None:
    """Deny a pending request."""
    with _client() as client:
        resp = client.post(f"/v1/capabilities/approvals/{request_id}", json={"approved": False})
        resp.raise_for_status()
        out = resp.json()
    console.print(f"Request {out.get('request_id', request_id)} denied.")
