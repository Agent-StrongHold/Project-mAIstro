"""The SPA catch-all must not serve files outside the static root.

`AuthMiddleware` only authenticates paths starting with `/v1/`
(`middleware/auth.py`), so `main.py`'s `@app.get("/{full_path:path}")` fallback
is reachable **unauthenticated**. Before the containment check, it did:

    fp = STATIC_DIR / full_path
    if fp.is_file():
        return FileResponse(fp)

`Path.__truediv__` discards the left operand when the right one is absolute, so
`STATIC_DIR / "/home/appuser/.conductor/credential_master.key"` is that path
verbatim — no dot-segments involved, and the `v1/` prefix guard never fires for
it. That made the credential master key, the encrypted credential store and the
session database readable by anyone who could reach the port.

These tests pin both escape shapes (absolute operand, `..` traversal) plus the
symlink case, and assert the legitimate happy path still works.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def static_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """An app whose SPA fallback serves from a real, isolated static root.

    `spa_fallback` is only registered when `STATIC_DIR.is_dir()`, and the route
    closes over the resolved root at registration time — so the patch has to
    land before `create_app()` runs.
    """
    static_root = tmp_path / "dist"
    static_root.mkdir()
    (static_root / "index.html").write_text("<!doctype html><title>spa</title>")
    (static_root / "app.js").write_text("console.log('real asset')")

    # The kind of file the traversal was able to read: outside the static root,
    # readable by the server process.
    secret = tmp_path / "secret" / "credential_master.key"
    secret.parent.mkdir()
    secret.write_text("SUPER-SECRET-MASTER-KEY")

    main = importlib.import_module("main")
    monkeypatch.setattr(main, "STATIC_DIR", static_root)

    return TestClient(main.create_app()), static_root, secret


def test_serves_a_real_asset_from_the_static_root(static_app):
    """Containment must not break the thing the route exists for."""
    client, _static_root, _secret = static_app

    response = client.get("/app.js")

    assert response.status_code == 200
    assert "real asset" in response.text


def test_unknown_path_still_falls_back_to_the_spa_shell(static_app):
    client, _static_root, _secret = static_app

    response = client.get("/some/client/side/route")

    assert response.status_code == 200
    assert "<title>spa</title>" in response.text


def _spa_fallback_handler(app):
    """The registered `spa_fallback` callable, for calling with a raw value.

    Going through TestClient is not sufficient for the two traversal shapes
    below: httpx normalizes `..` segments and collapses duplicate slashes in the
    URL before the request is ever built, so the handler never receives the
    hostile string. (Verified: with the containment check reverted, both cases
    still returned the SPA shell through the client while the symlink case
    leaked — i.e. a client-only test would have passed against vulnerable code.)
    A proxy, a hand-written client, or any non-normalizing intermediary can send
    these, so the handler itself is the correct unit under test.
    """
    for route in app.routes:
        if getattr(route, "name", None) == "spa_fallback":
            return route.endpoint
    raise AssertionError("spa_fallback route was not registered")


@pytest.mark.asyncio
async def test_absolute_path_operand_does_not_escape_the_static_root(static_app):
    """The actual reported primitive: an absolute `full_path` discards STATIC_DIR.

    `Path("/static") / "/home/.../credential_master.key"` is the key path
    verbatim — no dot-segments, and the `v1/` guard does not fire.
    """
    client, static_root, secret = static_app
    handler = _spa_fallback_handler(client.app)

    response = await handler(str(secret))

    assert Path(response.path).resolve() != secret.resolve()
    assert Path(response.path).resolve() == (static_root / "index.html").resolve()


@pytest.mark.asyncio
async def test_dot_segment_traversal_does_not_escape_the_static_root(static_app):
    client, static_root, secret = static_app
    handler = _spa_fallback_handler(client.app)

    response = await handler(f"../secret/{secret.name}")

    assert Path(response.path).resolve() != secret.resolve()
    assert Path(response.path).resolve() == (static_root / "index.html").resolve()


def test_symlink_out_of_the_static_root_is_not_followed(static_app):
    """resolve() before the boundary check is what closes this one.

    A containment check done on the unresolved path would pass here and then
    serve the link target.
    """
    client, static_root, secret = static_app
    (static_root / "leak.key").symlink_to(secret)

    response = client.get("/leak.key")

    assert "SUPER-SECRET-MASTER-KEY" not in response.text
