"""Tests for the OpenAI-compatible /v1/chat/completions endpoint.

Evidence: Open WebUI talks to maistro-engine via the OpenAI chat-completions
contract. Both streaming (SSE) and non-streaming modes must translate
conductor errors (timeout, LLM provider error, generic exception) into the
correct HTTP status / SSE error event.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from maistro.agents.types import ConductorOutput, LLMProviderError
from maistro_server.api.chat_completions import (
    ChatCompletionRequest,
    ChatMessage,
    _extract_user_message,
)
from maistro_server.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _output(answer: str = "the answer") -> ConductorOutput:
    return ConductorOutput(final_answer=answer, success=True)


class TestExtractUserMessage:
    def test_extracts_last_user_message(self) -> None:
        req = ChatCompletionRequest(
            messages=[
                ChatMessage(role="system", content="be helpful"),
                ChatMessage(role="user", content="first"),
                ChatMessage(role="assistant", content="reply"),
                ChatMessage(role="user", content="second"),
            ]
        )
        assert _extract_user_message(req) == "second"

    def test_defaults_when_no_user_message(self) -> None:
        req = ChatCompletionRequest(messages=[ChatMessage(role="system", content="x")])
        assert _extract_user_message(req) == "No task specified"

    def test_skips_user_message_with_none_content(self) -> None:
        req = ChatCompletionRequest(
            messages=[
                ChatMessage(role="user", content="real"),
                ChatMessage(role="user", content=None),
            ]
        )
        assert _extract_user_message(req) == "real"


class TestNonStreamingChatCompletions:
    def test_returns_conductor_answer(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(return_value=_output("42")),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "what is the answer"}]},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "42"
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["finish_reason"] == "stop"

    def test_falls_back_when_no_final_answer(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(return_value=ConductorOutput(final_answer="", success=True)),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "Task completed successfully."

    def test_timeout_returns_504(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(side_effect=TimeoutError()),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
        assert response.status_code == 504
        assert response.json()["error"]["message"] == "LLM call timed out"

    def test_llm_provider_error_returns_502(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(side_effect=LLMProviderError("upstream blew up")),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
        assert response.status_code == 502
        # Upstream detail must NOT be echoed to the client (June audit 3.5);
        # it belongs in the server log only.
        message = response.json()["error"]["message"]
        assert "upstream blew up" not in message
        assert message == "LLM provider error"

    def test_generic_exception_returns_500(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(side_effect=RuntimeError("kaboom")),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
        assert response.status_code == 500
        assert response.json()["error"]["message"] == "Internal server error"

    def test_model_field_echoed(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(return_value=_output("ok")),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "maistro-tier-3",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        assert response.json()["model"] == "maistro-tier-3"


class TestStreamingChatCompletions:
    def _parse_sse(self, body: str) -> list[dict]:
        events = []
        for line in body.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :]
            if payload == "[DONE]":
                events.append({"done": True})
                continue
            events.append(json.loads(payload))
        return events

    def test_streams_role_content_and_done(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(return_value=_output("hi there")),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={
                    "stream": True,
                    "messages": [{"role": "user", "content": "say hi"}],
                },
            )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = self._parse_sse(response.text)

        # First event: role chunk.
        assert events[0]["choices"][0]["delta"]["role"] == "assistant"
        # Last two events: finish chunk then [DONE].
        assert events[-2]["choices"][0]["finish_reason"] == "stop"
        assert events[-1] == {"done": True}
        # Content chunks reconstruct the full answer.
        content = "".join(
            e["choices"][0]["delta"].get("content") or "" for e in events[1:-2] if "choices" in e
        )
        assert content == "hi there"

    def test_streaming_timeout_emits_error_event(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(side_effect=TimeoutError()),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
            )
        events = self._parse_sse(response.text)
        error_events = [e for e in events if "error" in e]
        assert len(error_events) == 1
        assert error_events[0]["error"]["type"] == "timeout"
        assert events[-1] == {"done": True}

    def test_streaming_llm_provider_error_emits_error_event(self, client: TestClient) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(side_effect=LLMProviderError("nope")),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
            )
        events = self._parse_sse(response.text)
        error_events = [e for e in events if "error" in e]
        assert len(error_events) == 1
        assert error_events[0]["error"]["type"] == "upstream_error"

    def test_streaming_generic_exception_emits_internal_error_event(
        self, client: TestClient
    ) -> None:
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
            )
        events = self._parse_sse(response.text)
        error_events = [e for e in events if "error" in e]
        assert len(error_events) == 1
        assert error_events[0]["error"]["type"] == "internal_error"

    def test_streaming_chunks_long_answer(self, client: TestClient) -> None:
        long_answer = "x" * 45  # STREAM_CHUNK_SIZE is 20, so this spans 3 chunks.
        with patch(
            "maistro_server.api.chat_completions.run_task",
            AsyncMock(return_value=_output(long_answer)),
        ):
            response = client.post(
                "/v1/chat/completions",
                json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
            )
        events = self._parse_sse(response.text)
        content_events = [
            e for e in events if "choices" in e and e["choices"][0]["delta"].get("content")
        ]
        assert len(content_events) == 3
        reconstructed = "".join(e["choices"][0]["delta"]["content"] for e in content_events)
        assert reconstructed == long_answer
