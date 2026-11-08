"""Contract the Approvals UI (#2278) depends on — same doors as CLI.

No parallel store: capability inbox is `/v1/capabilities/approvals`, HITL is
`/v1/hitl/pending`. These tests pin shape + auth so the SPA cannot drift onto
a private authority.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from main import app

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CLI_APPROVALS = _REPO_ROOT / "packages/maistro-core/src/maistro/cli/_approvals.py"
_UI_LIB = _REPO_ROOT / "packages/hive-conductor/frontend/src/lib/approvals.ts"
_UI_PAGE = _REPO_ROOT / "packages/hive-conductor/frontend/src/pages/Approvals.tsx"


def test_capability_approvals_list_shape_matches_cli(admin_client: TestClient) -> None:
    r = admin_client.get("/v1/capabilities/approvals")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "pending" in body
    assert isinstance(body["pending"], list)
    for item in body["pending"]:
        assert "request_id" in item
        assert "action" in item
        # Fields `maistro approvals list` prints — UI must see the same set.
        assert "tier" in item
        assert "requester" in item


def test_capability_approvals_foreign_id_404(admin_client: TestClient) -> None:
    r = admin_client.post(
        "/v1/capabilities/approvals/does-not-exist-ui-contract",
        json={"approved": True},
    )
    assert r.status_code == 404


def test_capability_resolve_body_matches_cli_approve_and_deny(
    admin_client: TestClient,
) -> None:
    """AC-2: UI posts the same ``{"approved": bool}`` body as ``maistro approvals``."""
    for approved in (True, False):
        r = admin_client.post(
            "/v1/capabilities/approvals/does-not-exist-cli-body",
            json={"approved": approved},
        )
        # Unknown id still fail-closed; body must be accepted (not 422).
        assert r.status_code == 404, r.text


def test_anonymous_cannot_list_or_resolve_capability_approvals() -> None:
    anon = TestClient(app)
    assert anon.get("/v1/capabilities/approvals").status_code == 401
    assert anon.post("/v1/capabilities/approvals/x", json={"approved": False}).status_code == 401


def test_hitl_pending_is_list_or_unavailable(admin_client: TestClient) -> None:
    """UI treats 200 list and 503 spine-unavailable as honest answers."""
    r = admin_client.get("/v1/hitl/pending")
    assert r.status_code in (200, 403, 503), r.text
    if r.status_code == 200:
        assert isinstance(r.json(), list)


def test_hitl_foreign_ids_fail_closed_on_answer_and_cancel(
    admin_client: TestClient,
) -> None:
    """AC-3: SPA answer/cancel of a missing/foreign Run+node never invents success.

    With a spine wired, the door returns 404 (indistinguishable from foreign).
    Without one, 503 — same honest refusal the Approvals page already treats
    as an error toast, not a parallel local queue.
    """
    missing_run = "does-not-exist-hitl-ui-contract"
    missing_node = "ask"
    answer = admin_client.post(
        f"/v1/hitl/{missing_run}/{missing_node}/answer",
        json={"decision": "approved"},
    )
    cancel = admin_client.post(f"/v1/hitl/{missing_run}/{missing_node}/cancel", json={})
    assert answer.status_code in (404, 503), answer.text
    assert cancel.status_code in (404, 503), cancel.text


def test_ui_and_cli_share_capability_approval_doors() -> None:
    """AC-1/AC-2/AC-4: typed SPA helpers and ``maistro approvals`` hit the same paths."""
    cli = _CLI_APPROVALS.read_text(encoding="utf-8")
    ui_lib = _UI_LIB.read_text(encoding="utf-8")
    ui_page = _UI_PAGE.read_text(encoding="utf-8")

    assert 'client.get("/v1/capabilities/approvals")' in cli
    assert 'f"/v1/capabilities/approvals/{request_id}"' in cli
    assert 'json={"approved": True}' in cli
    assert 'json={"approved": False}' in cli

    assert 'CAPABILITY_APPROVALS_PATH = "/v1/capabilities/approvals"' in ui_lib
    assert 'HITL_PENDING_PATH = "/v1/hitl/pending"' in ui_lib
    assert "/v1/capabilities/approvals/${encodeURIComponent(requestId)}" in ui_lib
    assert "/v1/hitl/${encodeURIComponent(runId)}/${encodeURIComponent(nodeId)}/answer" in ui_lib
    assert "/v1/hitl/${encodeURIComponent(runId)}/${encodeURIComponent(nodeId)}/cancel" in ui_lib

    # No parallel approvals authority in the page — only the shared lib paths.
    assert 'from "../lib/approvals"' in ui_page
    assert "/v1/approvals" not in ui_page
    assert "localStorage" not in ui_page
    assert "indexedDB" not in ui_page
