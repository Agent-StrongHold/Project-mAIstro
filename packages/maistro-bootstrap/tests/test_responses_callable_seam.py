"""The LiteLLM post path rides the guarded sync seam (ADR-102 AC-1).

The builder tests stub `responses_callable._post`, which proves the callers but
never executes the seam itself. These tests drive the real body: an destination
the operator never configured is refused by the central guard before any socket
opens, and the configured gateway flows through `maistro.http.sync_client` —
with `_post` registering the operator origin the guard requires.
"""

from __future__ import annotations

import httpx
import pytest

from maistro.http import sync_client as real_sync_client
from maistro.security.outbound import (
    OutboundBlockedError,
    current_outbound_policy,
    reset_outbound_policy,
)
from maistro_bootstrap.builders import responses_callable as rc


@pytest.fixture(autouse=True)
def _isolated_policy():
    reset_outbound_policy()
    yield
    reset_outbound_policy()


def _guarded_mock_transport(monkeypatch: pytest.MonkeyPatch, handler):
    def factory(**kwargs):
        return real_sync_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(rc, "sync_client", factory)


def test_post_refuses_a_destination_the_operator_never_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITELLM_URL", "http://gw.test:4000")
    with pytest.raises(OutboundBlockedError):
        rc._post("http://127.0.0.1:9/v1/chat/completions", json={}, headers={}, timeout=1.0)
    assert not current_outbound_policy().allows("http://127.0.0.1:9/v1/chat/completions")


def test_post_sends_through_the_guarded_client_and_registers_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITELLM_URL", "http://gw.test:4000")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization", "")
        seen["body"] = str(request.read(), encoding="utf-8")
        return httpx.Response(200, json={"ok": True})

    _guarded_mock_transport(monkeypatch, handler)

    response = rc._post(
        "http://gw.test:4000/v1/chat/completions",
        json={"model": "m", "messages": []},
        headers={"Authorization": "Bearer sk-test"},
        timeout=1.0,
    )

    assert response.status_code == 200
    assert seen["url"] == "http://gw.test:4000/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert '"model": "m"' in seen["body"] or '"model":"m"' in seen["body"]
    # The helper registered the operator's configured origin itself: the policy
    # was empty before the call (see the autouse fixture).
    assert current_outbound_policy().allows("http://gw.test:4000/v1/chat/completions")
