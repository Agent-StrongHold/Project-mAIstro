from __future__ import annotations


def test_feed_empty(authed_client):
    r = authed_client.get("/v1/feed")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_human_cannot_publish(authed_client):
    r = authed_client.post("/v1/feed", json={"kind": "blog", "title": "x", "body": "y"})
    # No service key on a human session → 401 from the scope dependency.
    assert r.status_code == 401


def test_service_publishes_and_human_reads(turing_service_client, authed_client):
    r = turing_service_client.post(
        "/v1/feed",
        json={"kind": "blog", "title": "First post", "body": "hello world"},
    )
    assert r.status_code == 201
    artifact_id = r.json()["artifact_id"]

    listed = authed_client.get("/v1/feed").json()
    assert listed["total"] == 1
    assert listed["items"][0]["title"] == "First post"

    single = authed_client.get(f"/v1/feed/{artifact_id}")
    assert single.status_code == 200
    assert single.json()["body"] == "hello world"


def test_unknown_kind_rejected(turing_service_client):
    r = turing_service_client.post("/v1/feed", json={"kind": "nonsense", "title": "x", "body": "y"})
    assert r.status_code == 400


def test_pagination_and_kind_filter(turing_service_client, authed_client):
    for i in range(3):
        turing_service_client.post("/v1/feed", json={"kind": "blog", "title": f"b{i}", "body": "x"})
    turing_service_client.post("/v1/feed", json={"kind": "emotion", "title": "e0", "body": "x"})

    page = authed_client.get("/v1/feed", params={"limit": 2}).json()
    assert page["total"] == 4
    assert len(page["items"]) == 2

    blogs = authed_client.get("/v1/feed", params={"kind": "blog"}).json()
    assert blogs["total"] == 3


def test_missing_artifact_404(authed_client):
    assert authed_client.get("/v1/feed/does-not-exist").status_code == 404
