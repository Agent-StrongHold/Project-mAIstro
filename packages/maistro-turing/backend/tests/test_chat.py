from __future__ import annotations


def test_chat_requires_auth(client):
    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 401


def test_empty_message_rejected(authed_client):
    assert authed_client.post("/v1/chat", json={"message": "  "}).status_code == 400


def test_chat_with_fake_provider(authed_client, monkeypatch):
    # The dev provider bridge has no LLM client; inject a fake so the real
    # TuringChatSession path runs end-to-end instead of returning 503.
    from ..state import get_state

    st = get_state()
    monkeypatch.setattr(st.provider, "complete", lambda *a, **k: "hello from turing", raising=True)

    r = authed_client.post("/v1/chat", json={"message": "hey"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "hello from turing"
    assert body["session_id"]


def test_chat_without_llm_returns_503(authed_client):
    # No LLM client wired → TuringChatSession raises RuntimeError → 503.
    r = authed_client.post("/v1/chat", json={"message": "hey"})
    assert r.status_code == 503
