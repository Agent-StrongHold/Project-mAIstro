"""Contract the Approvals UI (#2278) depends on — same doors as CLI.

No parallel store: capability inbox is `/v1/capabilities/approvals`, HITL is
`/v1/hitl/pending`. These tests pin shape + auth so the SPA cannot drift onto
a private authority.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


def test_capability_approvals_list_shape_matches_cli(admin_client: TestClient) -> None:
    r = admin_client.get("/v1/capabilities/approvals")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "pending" in body
    assert isinstance(body["pending"], list)
    for item in body["pending"]:
        assert "request_id" in item
        assert "action" in item


def test_capability_approvals_foreign_id_404(admin_client: TestClient) -> None:
    r = admin_client.post(
        "/v1/capabilities/approvals/does-not-exist-ui-contract",
        json={"approved": True},
    )
    assert r.status_code == 404


def test_anonymous_cannot_list_or_resolve_capability_approvals() -> None:
    anon = TestClient(app)
    assert anon.get("/v1/capabilities/approvals").status_code == 401
    assert (
        anon.post("/v1/capabilities/approvals/x", json={"approved": False}).status_code == 401
    )


def test_hitl_pending_is_list_or_unavailable(admin_client: TestClient) -> None:
    """UI treats 200 list and 503 spine-unavailable as honest answers."""
    r = admin_client.get("/v1/hitl/pending")
    assert r.status_code in (200, 403, 503), r.text
    if r.status_code == 200:
        assert isinstance(r.json(), list)
