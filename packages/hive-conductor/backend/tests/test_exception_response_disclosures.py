"""Internal exception diagnostics must not cross public route boundaries."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

SECRET = "postgresql://operator:private-password@internal-db/private/path"


def test_health_router_diagnostics_are_private():
    from routes.health import _optional_routers_state

    app = SimpleNamespace(
        state=SimpleNamespace(optional_routers={"routes.design": SECRET, "routes.audit": None})
    )
    result = _optional_routers_state(app)
    assert result == {
        "routes.design": "router initialization failed; see server logs",
        "routes.audit": None,
    }


def test_evolution_stored_diagnostics_are_private(monkeypatch):
    import services.evolution as service
    from routes.evolution import evolution_status

    raw = {
        "last_error": SECRET,
        "availability_reason": SECRET,
        "last_run_id": "run-1",
        "cycle_count": 3,
    }
    monkeypatch.setattr(
        service, "get_evolution_service", lambda: SimpleNamespace(status=lambda: raw)
    )
    result = evolution_status()
    assert SECRET not in str(result)
    assert result["last_run_id"] == "run-1"
    assert result["cycle_count"] == 3
    assert raw["last_error"] == SECRET


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unexpected", "canonical", "unavailable", "validation"])
async def test_evolution_error_contract(monkeypatch, kind):
    import services.evolution as service
    from routes.evolution import trigger_cycle

    from maistro.runs.model import RunStatus

    async def fail(**kwargs):
        if kind == "canonical":
            raise service.CanonicalEvolutionRunError(
                run_id="run-1", status=RunStatus.FAILED, diagnostic=SECRET
            )
        if kind == "unavailable":
            raise service.EvolutionUnavailableError(SECRET, availability="degraded")
        if kind == "validation":
            raise HTTPException(status_code=422, detail="invalid cycle selection")
        raise ValueError(SECRET)

    monkeypatch.setattr(
        service, "get_evolution_service", lambda: SimpleNamespace(_run_one_cycle=fail)
    )
    with pytest.raises(HTTPException) as caught:
        await trigger_cycle(SimpleNamespace(state=SimpleNamespace()))
    assert SECRET not in str(caught.value.detail)
    assert caught.value.status_code == {"unavailable": 503, "validation": 422}.get(kind, 500)
    if kind == "canonical":
        assert caught.value.detail["run_id"] == "run-1"
    if kind == "validation":
        assert caught.value.detail == "invalid cycle selection"


@pytest.mark.asyncio
async def test_rsi_policy_diagnostics_are_private(monkeypatch):
    import services.rsi as service
    from routes.rsi import StartRunBody, start_run
    from services import rsi_execution_policy as policy

    monkeypatch.setattr(service, "get_rsi_service", lambda: SimpleNamespace())

    def fail(*args):
        raise policy.RsiPolicyError(SECRET)

    monkeypatch.setattr(policy, "resolve_repo", fail)
    with pytest.raises(HTTPException) as caught:
        await start_run(StartRunBody(repo_path="/repo"))
    assert caught.value.status_code == 400
    assert SECRET not in caught.value.detail
