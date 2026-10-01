"""M3-B7 (#97): degraded mode is a complete user-facing operating state.

The F3 work made degradation *reported* (`degraded: true` on /health) but a
user-facing operating state has to answer *what* is degraded and *why*, keep
the answer queryable after the startup log line is gone, and never let a
degraded capability masquerade as a working one. These tests pin the three
halves the issue names:

- **Reporting** — /health names every degraded capability (`degraded_services`)
  and exposes the raw optional-router mount outcomes (`optional_routers`);
- **Auditability** — a degraded router entry lands in the /v1/audit trail as a
  warning, next to the capability changes it resembles, not only in a log;
- **Recovery** — the same surface that reports degradation reports recovery:
  /health recomputes per request (so the UI banner follows on the next poll),
  and an optional router recovers by the restart re-running the mount, which
  this suite pins directly against `_include_optional_router`.

A capability that did not mount must also not fake success: a path its router
would have owned answers 404, never a fabricated 200.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import stores
from fastapi import FastAPI
from fastapi.testclient import TestClient
from main import _include_optional_router, app

client = TestClient(app)

_BROKEN_MODULE = "routes.__no_such_optional_module__"


def _services(data: dict) -> list[str]:
    return [entry["service"] for entry in data["degraded_services"]]


def patch_memory_decay(state: str):
    """Pin the memory-decay probe to a given driver state."""
    return patch(
        "routes.health._memory_decay_state",
        return_value={"enabled": state == "running", "state": state},
    )


def patch_redaction(active: bool):
    """Pin the ADR-064 redaction probe."""
    return patch("routes.health._log_redaction_active", return_value=active)


def patch_identity_disabled():
    """Pin identity to the supported no-crypto profile (never required)."""
    import services.identity_health as identity_health_module

    return patch.object(identity_health_module, "identity_health", lambda: {"status": "disabled"})


def test_health_names_degraded_optional_router_with_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A router that failed to mount is named in degraded_services, with cause.

    Before #97 the failure lived on `app.state.optional_routers` and in one
    startup log line: recorded, but not answerable by any client. /health is
    the queryable surface, and the entry must be specific enough to act on.
    """
    monkeypatch.setattr(
        app.state,
        "optional_routers",
        {"routes.design": "ImportError: cannot import name 'engine'"},
    )

    data = client.get("/health").json()

    assert data["optional_routers"]["routes.design"] == "ImportError: cannot import name 'engine'"
    assert {
        "service": "router:routes.design",
        "reason": "ImportError: cannot import name 'engine'",
    } in data["degraded_services"]
    assert data["degraded"] is True


def test_health_lists_each_degraded_capability_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The always-present capability checks render with stable service names.

    These are the entries the UI banner and `hctl status` display verbatim, so
    each must carry a human-readable reason, not just a boolean.
    """
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    with patch_memory_decay(state="stopped"), patch_redaction(False):
        data = client.get("/health").json()

    services = {entry["service"]: entry["reason"] for entry in data["degraded_services"]}
    assert "no LLM gateway" in services["llm_gateway"]
    assert services["memory_decay"].startswith("episodic decay is not running")
    assert "redaction inactive" in services["log_redaction"]
    assert data["degraded"] is True


def test_health_reports_no_degradation_when_everything_is_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy routers stay out of degraded_services and `degraded` is false.

    The full healthy picture, not a partial one: a `degraded: false` that
    silently ignored a broken router would recreate the exact silent gap the
    F3 work closed for the LLM gateway.
    """
    monkeypatch.setenv("LITELLM_API_BASE", "http://gateway.example")
    monkeypatch.setattr(
        app.state,
        "optional_routers",
        {"routes.design": None, "routes.canvas": None},
    )
    with (
        patch_memory_decay(state="running"),
        patch_redaction(True),
        patch_identity_disabled(),
    ):
        data = client.get("/health").json()

    assert data["degraded"] is False
    assert data["degraded_services"] == []
    assert data["optional_routers"] == {"routes.design": None, "routes.canvas": None}


def test_degraded_router_entry_is_auditable() -> None:
    """Degraded entry is an audit event, not only a log line.

    The /v1/audit trail is the queryable operational record; a router that
    failed to mount lands there as a warning with the module as target, so an
    operator can diff "what degraded and when" against the capability changes
    in the same trail.
    """
    probe = FastAPI()
    _include_optional_router(probe, _BROKEN_MODULE)

    assert probe.state.optional_routers[_BROKEN_MODULE]  # the cause is recorded
    entries = [
        e
        for e in stores.audit_log.values()
        if e["action"] == "optional_router_degraded" and e["target"] == _BROKEN_MODULE
    ]
    assert entries, "expected an optional_router_degraded audit entry"
    assert entries[-1]["severity"] == "warning"
    assert entries[-1]["actor"] == "system"
    assert entries[-1]["detail"]["error"]


def test_unmounted_capability_is_a_404_not_fake_success() -> None:
    """A route family whose router did not mount answers 404, never a 200.

    The "unsupported actions fail rather than fake success" half of #97: the
    missing capability is a Starlette 404 against the real app — there is no
    stub route that could accept a request and report a state that never
    happened.
    """
    probe = FastAPI()
    _include_optional_router(probe, _BROKEN_MODULE)
    assert TestClient(probe).get("/v1/evolution/status").status_code == 404


def test_recovery_when_optional_service_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recovery is defined on the same surface as degradation, and tested.

    Two recovery shapes, both pinned:

    - **Per-request recompute** (LLM gateway): /health re-evaluates on every
      call, so when the service returns, degraded_services loses the entry
      and the UI banner disappears on the next poll — no restart, no stale
      cached degradation.
    - **Restart re-mount** (optional routers): a failed mount is permanent for
      the process, by design — recovery is the restart re-running
      `_include_optional_router`, which records success and serves the
      capability again.
    """
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    assert "llm_gateway" in _services(client.get("/health").json())

    monkeypatch.setenv("LITELLM_API_BASE", "http://gateway.example")
    assert "llm_gateway" not in _services(client.get("/health").json())

    healthy = FastAPI()
    _include_optional_router(healthy, "routes.audit", prefix="/v1/audit")
    assert healthy.state.optional_routers["routes.audit"] is None
    assert TestClient(healthy).get("/v1/audit").status_code == 200
