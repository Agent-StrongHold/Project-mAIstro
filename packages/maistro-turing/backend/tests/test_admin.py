from __future__ import annotations


def test_admin_endpoints_require_admin(authed_client):
    # Logged-in non-admin user → 403.
    assert authed_client.get("/v1/admin/self-model").status_code == 403
    assert authed_client.patch("/v1/admin/mood", json={"valence": 0.1}).status_code == 403


def test_admin_endpoints_require_human_not_service(turing_service_client):
    # Service key is not a human session → 401 (require_user fails).
    assert turing_service_client.get("/v1/admin/self-model").status_code == 401


def test_admin_get_self_model(admin_client):
    r = admin_client.get("/v1/admin/self-model")
    assert r.status_code == 200
    body = r.json()
    assert "mood" in body
    assert len(body["facets"]) == 24


def test_admin_patch_mood(admin_client):
    r = admin_client.patch("/v1/admin/mood", json={"valence": 0.9, "focus": 0.1})
    assert r.status_code == 200
    assert r.json()["valence"] == 0.9
    assert r.json()["focus"] == 0.1


def test_admin_patch_mood_out_of_range(admin_client):
    assert admin_client.patch("/v1/admin/mood", json={"valence": 2.0}).status_code == 422


def test_admin_patch_facet(admin_client):
    r = admin_client.patch("/v1/admin/facet", json={"facet_id": "creativity", "score": 4.5})
    assert r.status_code == 200
    assert r.json()["score"] == 4.5
    snap = admin_client.get("/v1/admin/self-model").json()
    assert snap["facets"]["creativity"] == 4.5


def test_admin_patch_unknown_facet(admin_client):
    r = admin_client.patch("/v1/admin/facet", json={"facet_id": "nope", "score": 3.0})
    assert r.status_code == 400


def test_admin_patch_empty_mood(admin_client):
    assert admin_client.patch("/v1/admin/mood", json={}).status_code == 400
