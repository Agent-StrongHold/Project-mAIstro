"""Docker id/name validation on the container routes (review finding C3).

Every handler in `routes/containers.py` interpolates its `container_id` path
parameter straight into a Docker Engine API URL spoken over the host socket,
which has no authentication of its own. A value that is not a container
reference — `..`, or anything carrying a query separator — addresses a
*different* daemon endpoint after URL normalisation.

These fail without the fix: previously the handlers reached the socket check and
returned 503 (no Docker in CI) for any input at all, so nothing distinguished a
valid id from a traversal attempt. Validation runs before the socket check
precisely so the boundary is testable without a daemon.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Values that must never reach the URL builder. `..` normalises the request path
# up out of /containers/; the `?`/`#` forms graft a query or fragment onto the
# daemon call; the space and slash forms are simply not identifiers.
_REJECTED = [
    "..",
    ".",
    # Reaches the validator as a literal "?" / "#": uvicorn percent-decodes the
    # path before Starlette routes it, so these are what the handler actually
    # sees for `/v1/containers/x%3Fall%3D1`.
    "x?all=1&y=",
    "abc#frag",
    "a%2Fb",
    "user:pass@host",
    "-leading-dash",
    "_leading-underscore",
    "has space",
    "",
]

_ACCEPTED = [
    "a" * 12,
    "0123456789abcdef" * 4,  # 64-char hex, a full Docker id
    "my_container-1.0",
    "postgres",
]


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
@pytest.mark.parametrize("bad", _REJECTED)
def test_validator_rejects_non_identifiers(bad: str) -> None:
    from fastapi import HTTPException
    from routes.containers import _validate_container_id

    with pytest.raises(HTTPException) as exc:
        _validate_container_id(bad)
    assert exc.value.status_code == 400


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
@pytest.mark.parametrize("good", _ACCEPTED)
def test_validator_accepts_real_identifiers(good: str) -> None:
    from routes.containers import _validate_container_id

    assert _validate_container_id(good) == good


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
def test_get_container_rejects_bad_id_over_http(authed_client: TestClient) -> None:
    """400 rather than 503: the request is refused before Docker is consulted.

    A leading-dash id is used rather than a percent-encoded traversal because
    the exact decoding of `%2e%2e` varies between client and server; the point
    under test is that the route rejects a non-identifier, and the traversal
    strings are covered directly by the unit parametrization above.
    """
    r = authed_client.get("/v1/containers/-leading-dash")
    assert r.status_code == 400, r.text


class _FakeResponse:
    status_code = 200
    text = "log line"

    def raise_for_status(self) -> None:
        return None


class _RecordingClient:
    """Stands in for the Docker socket client and records the URL it is given."""

    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        self._urls.append(url)
        return _FakeResponse()


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
def test_logs_tail_is_clamped(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """`tail` is interpolated too; an unbounded value is a memory amplifier."""
    import routes.containers as containers

    urls: list[str] = []
    monkeypatch.setattr(containers.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(containers, "_docker_client", lambda: _RecordingClient(urls))

    r = admin_client.get("/v1/containers/postgres/logs?tail=999999999")
    assert r.status_code == 200, r.text
    assert len(urls) == 1
    assert "tail=10000" in urls[0], urls[0]
    assert "999999999" not in urls[0]
