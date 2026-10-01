"""Success-shaped no-op route elimination (#389) — contract tests.

Every route the #389 audit named as canned/no-op/empty must now either change
durable state a query can observe, return seeded non-empty data from its
canonical owner, or refuse with an explicit unsupported status. These tests
prove each disposition over HTTP, against the same stores production reads,
and hold the distinctness rule: empty-valid, unavailable, unimplemented,
failed, and unauthorized never share a response.

The audit inventory itself lives in `docs/api/route-contract-inventory.md`;
the CI gate that refuses new canned handlers is `scripts/check-api-route-contracts.py`.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import Any

import httpx
import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from routes.audit import log_audit  # noqa: E402
from services import settings_store  # noqa: E402


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_audit_log():
    _clear(stores.audit_log)
    yield
    _clear(stores.audit_log)


class _RecordingStore:
    """An in-process settings record store the test can write behind."""

    def __init__(self, *, document: str | None = None) -> None:
        self._document = document

    @property
    def durable(self) -> bool:
        return True

    def read(self) -> str | None:
        return self._document

    def write(self, document: str) -> None:
        self._document = document


class _UnavailableStore:
    """A settings store whose reads fail — the unavailable dependency."""

    durable = True

    def read(self) -> str:
        raise RuntimeError("record store is down")

    def write(self, document: str) -> None:  # pragma: no cover - never reached
        raise RuntimeError("record store is down")


@pytest.fixture
def recording_store() -> Any:
    recording = _RecordingStore()
    settings_store.reset(store=recording)
    yield recording
    settings_store.reset()


@pytest.fixture
def config_admin(admin_client):
    """An admin client: settings writes need config.write; admin holds all scopes."""
    return admin_client


# --------------------------------------------------------------------------- #
# POST /v1/settings/reload — the reload must actually re-read the store
# --------------------------------------------------------------------------- #


def test_settings_reload_reflects_an_out_of_band_write(
    recording_store: _RecordingStore, config_admin: Any
) -> None:
    """The reload drops the cache and re-reads: a state change is observable (#389).

    `POST /reload` used to return `{"status": "reloaded"}` without touching
    anything. Now a record edited behind the running process becomes visible
    without a restart, and the response carries the fresh revision so the
    caller can verify the reload happened.
    """
    before = config_admin.get("/v1/settings/record").json()
    # A fresh store seeds defaults without writing: revision 0 is valid here;
    # what matters is that the reload below advances past whatever it was.
    assert before["revision"] == settings_store.record().revision

    stored = settings_store.record()
    newer = stored.model_copy(
        update={
            "revision": stored.revision + 1,
            "values": stored.values.model_copy(update={"default_model": "out-of-band-model"}),
        }
    )
    recording_store.write(newer.model_dump_json())

    r = config_admin.post("/v1/settings/reload")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == stored.revision + 1
    assert body["values"]["default_model"] == "out-of-band-model"
    # The reloaded record is what subsequent reads see, too.
    assert config_admin.get("/v1/settings").json()["default_model"] == "out-of-band-model"


def test_settings_reload_with_unavailable_store_is_503(
    config_admin: Any,
) -> None:
    """A store that cannot be read is 503 — never a claimed reload (#389)."""
    settings_store.reset(store=_UnavailableStore())
    try:
        r = config_admin.post("/v1/settings/reload")
        assert r.status_code == 503
        assert "record store is down" in r.json()["detail"]
    finally:
        settings_store.reset()


# --------------------------------------------------------------------------- #
# GET /v1/settings/audit — the settings-change trail, from the durable log
# --------------------------------------------------------------------------- #


def test_settings_audit_empty_is_valid(config_admin: Any) -> None:
    """No settings writes recorded means `[]` — empty-valid, not a stub (#389)."""
    r = config_admin.get("/v1/settings/audit")
    assert r.status_code == 200
    assert r.json() == []


def test_settings_audit_returns_seeded_non_empty_data(config_admin: Any) -> None:
    """A settings write is followed by its audit entry — seeded query proof (#389).

    The writer (`log_audit`, the same function the PUT/PATCH routes call)
    seeds entries; the query must return them scoped to settings actions,
    newest first, honoring the limit. Non-settings actions stay out.
    """
    log_audit("settings_patch", "system", detail={"theme": "dark"})
    log_audit("login", "someone")
    log_audit("settings_update", "system", detail={"default_model": "m2"})

    r = config_admin.get("/v1/settings/audit")
    assert r.status_code == 200
    entries = r.json()
    assert [e["action"] for e in entries] == ["settings_update", "settings_patch"]

    one = config_admin.get("/v1/settings/audit", params={"limit": 1})
    assert one.status_code == 200
    assert len(one.json()) == 1
    assert one.json()[0]["action"] == "settings_update"


# --------------------------------------------------------------------------- #
# GET /v1/settings/quotas — one canonical owner with /v1/quotas/providers
# --------------------------------------------------------------------------- #


def _fake_get(routes_map: dict[str, object]):
    def _get(url: str, **kwargs: object) -> httpx.Response:
        for path, payload in routes_map.items():
            if path in url:
                if isinstance(payload, Exception):
                    raise payload
                return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
        return httpx.Response(404, json={}, request=httpx.Request("GET", url))

    return _get


def test_settings_quotas_serves_the_provider_panel(
    config_admin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/v1/settings/quotas` is the same LiteLLM-backed panel, not `{"providers": []}`."""
    monkeypatch.setenv("LITELLM_API_BASE", "http://litellm.test:4000")
    monkeypatch.setattr(
        httpx,
        "get",
        _fake_get(
            {
                "/global/spend/report": [
                    {
                        "model_details": [
                            {
                                "model": "gpt-4",
                                "total_input_tokens": 10,
                                "total_output_tokens": 5,
                                "usage": {"api_requests": 2},
                            }
                        ]
                    }
                ],
                "/model/info": {
                    "data": [{"model_name": "gpt-4", "model_info": {"litellm_provider": "openai"}}]
                },
            }
        ),
    )
    direct = config_admin.get("/v1/quotas/providers")
    assert direct.status_code == 200
    via_settings = config_admin.get("/v1/settings/quotas")
    assert via_settings.status_code == 200
    assert via_settings.json() == direct.json()
    assert via_settings.json()[0]["request_count"] == 2


def test_settings_quotas_unavailable_is_503(config_admin: Any, monkeypatch) -> None:
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("CONDUCTOR_ROUTER_URL", raising=False)
    r = config_admin.get("/v1/settings/quotas")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# GET /v1/schedules/history — fire receipts from the durable audit log
# --------------------------------------------------------------------------- #


def _workspace(owner: str, name: str) -> Any:
    from services.workspace_authority import create_workspace

    return asyncio.run(
        create_workspace(
            creator_user_id=owner,
            name=name,
            persona_template_id="default",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
    )


def _schedule(sid: str, *, user_id: str, workspace_id: str) -> None:
    from datetime import UTC, datetime

    from models.schemas import Schedule

    t = datetime.now(UTC)
    stores.schedules[sid] = Schedule(
        id=sid,
        user_id=user_id,
        workspace_id=workspace_id,
        project_id="",
        name=f"schedule-{sid}",
        description="",
        cron_expression="0 12 * * *",
        mission_template_id="tpl",
        enabled=True,
        timezone="UTC",
        max_runs=None,
        catchup_window_seconds=3600.0,
        last_run=None,
        last_run_id=None,
        next_run=None,
        created_at=t,
        updated_at=t,
    )


@pytest.fixture
def history_user():
    """A plain user (no scopes needed: history is a read) with cleanup."""
    import stores as s
    from fastapi.testclient import TestClient
    from main import app

    s.users["histuser"] = s.users["user"].model_copy(
        update={"id": "histuser", "username": "histuser"}
    )
    client = TestClient(app)
    r = client.post("/v1/auth/login", json={"username": "histuser", "password": "testpass"})
    assert r.status_code == 200
    yield client
    s.users.pop("histuser", None)


def test_schedule_history_empty_is_valid(history_user: Any) -> None:
    """No fires recorded means `[]` — empty-valid, not a stub (#389)."""
    r = history_user.get("/v1/schedules/history")
    assert r.status_code == 200
    assert r.json() == []


def test_schedule_history_returns_seeded_non_empty_data(history_user: Any) -> None:
    """Fire receipts a scheduler wrote are what history returns (#389).

    The route used to `return []` forever. The canonical scheduler writes a
    `schedule_fire` receipt and a `schedule_run` outcome (run id included)
    to the durable audit log per fire; the query returns them for schedules
    the caller can see.
    """
    ws = _workspace("histuser", "History schedules")
    foreign_ws = _workspace("someone-else", "Foreign schedules")
    _schedule("sch-mine", user_id="histuser", workspace_id=ws.id)
    _schedule("sch-foreign", user_id="someone-else", workspace_id=foreign_ws.id)
    log_audit(
        "schedule_fire",
        "system",
        target="sch-mine",
        detail={"scheduled_for": "2026-07-01T12:00:00+00:00", "catchup": False},
    )
    log_audit(
        "schedule_run",
        "system",
        target="sch-mine",
        detail={"dag_id": "tpl", "run_id": "run-123", "status": "completed"},
    )
    # Another Workspace's fire must not be visible to this caller.
    log_audit("schedule_fire", "system", target="sch-foreign", detail={})

    try:
        r = history_user.get("/v1/schedules/history")
        assert r.status_code == 200
        events = r.json()
        assert len(events) == 2
        assert all(e["target"] == "sch-mine" for e in events)
        # Newest first: the run outcome (written last) is the first entry.
        assert events[0]["action"] == "schedule_run"
        assert events[0]["detail"]["run_id"] == "run-123"
    finally:
        stores.schedules.pop("sch-mine", None)
        stores.schedules.pop("sch-foreign", None)


# --------------------------------------------------------------------------- #
# Explicitly unsupported operations refuse with 501 — distinct from failing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("post", "/v1/containers/build", {"name": "img", "dockerfile": "FROM python:3.12-slim"}),
        ("post", "/v1/containers/suggest", {"description": "a python app"}),
        ("post", "/v1/mcp/discover", {"url": "http://mcp.example.com"}),
        ("get", "/v1/rsi/models", None),
    ],
)
def test_unsupported_operations_are_501(
    config_admin: Any, method: str, path: str, json_body: dict | None
) -> None:
    """Canned success is replaced by an explicit refusal (#389).

    Each of these shipped a hard-coded success (`{"status": "building"}`, a
    stock Dockerfile, `{"tools": [], "status": "scanning"}`, a baked-in model
    catalog). Nothing implements them, so each now says so with `501` — the
    distinct status for unimplemented, never a fake success.
    """
    r = (
        config_admin.get(path)
        if method == "get"
        else getattr(config_admin, method)(path, json=json_body)
    )
    assert r.status_code == 501, r.text
    assert r.json()["detail"]


def test_mcp_scan_refuses_real_servers_with_501_and_keeps_404(config_admin: Any) -> None:
    """The 404 for an unknown server stays; a real server gets an honest 501."""
    missing = config_admin.post("/v1/mcp/servers/no-such-server/scan")
    assert missing.status_code == 404

    from models.schemas import MCPServer

    stores.mcp_servers["srv-x"] = MCPServer(
        id="srv-x",
        name="x",
        description="scan target",
        url="http://mcp.internal:8000",
        status="disconnected",
    )
    try:
        r = config_admin.post("/v1/mcp/servers/srv-x/scan")
        assert r.status_code == 501
        assert "not implemented" in r.json()["detail"]
    finally:
        stores.mcp_servers.pop("srv-x", None)


# --------------------------------------------------------------------------- #
# The API schema identifies preview and unsupported operations
# --------------------------------------------------------------------------- #


def test_openapi_marks_preview_and_unsupported_operations() -> None:
    """The schema itself says which operations are preview or unsupported (#389)."""
    from main import app

    schema = app.openapi()
    volatile = schema["paths"]["/v1/settings/volatile"]
    for op in ("get", "put", "delete"):
        assert "Preview" in volatile[op]["summary"]
    build = schema["paths"]["/v1/containers/build"]["post"]
    assert "not implemented" in build["description"]

    reload_op = schema["paths"]["/v1/settings/reload"]["post"]
    assert "durable store" in reload_op["description"]

    # Whitespace-normalized: FastAPI renders docstrings with source wrapping.
    volatile_desc = " ".join(volatile["get"]["description"].split())
    assert "never written to the durable record" in volatile_desc


# --------------------------------------------------------------------------- #
# The placeholder gate holds: no canned handlers remain shipped
# --------------------------------------------------------------------------- #


def test_placeholder_gate_reports_no_findings() -> None:
    """`scripts/check-api-route-contracts.py` passes on this tree (#389)."""
    import subprocess

    repo = _BACKEND.parents[2]
    script = repo / "scripts" / "check-api-route-contracts.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=repo,
    )
    assert result.returncode == 0, result.stdout + result.stderr
