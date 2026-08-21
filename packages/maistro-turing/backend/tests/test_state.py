from __future__ import annotations


def test_snapshot_requires_auth(client):
    assert client.get("/v1/state/snapshot").status_code == 401


def test_snapshot_shape(authed_client):
    r = authed_client.get("/v1/state/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["self_id"] == "turing"
    assert set(body["mood"]) >= {"valence", "arousal", "focus"}
    assert set(body["drives"]) == {
        "creative_urge",
        "curiosity",
        "diligence",
        "restlessness",
    }
    # Personality is the 6 HEXACO traits, each with 4 facets.
    assert len(body["personality"]) == 6
    total_facets = sum(len(v) for v in body["personality"].values())
    assert total_facets == 24


def test_snapshot_reflects_admin_mood_change(authed_client, admin_client):
    admin_client.patch("/v1/admin/mood", json={"valence": -0.5})
    body = authed_client.get("/v1/state/snapshot").json()
    assert body["mood"]["valence"] == -0.5
