"""`/v1/voice/intent` reports only what it can actually establish (#440).

The route advertised `actions_taken: list[dict]` -- the tools the utterance
invoked -- and could never put anything in it. Two independent reasons: it sent
`tools=None`, so no tool call was ever offered; and the local it returned was
built empty and never appended to. `intent` was documented as naming the first
tool invoked and only ever distinguished "the model said something" from "it
did not".

Those are completion claims nothing derives from evidence (#31). The M0
containment decision (#483/#484) is that no public Conductor route runs
model-driven tools until the Warden input/tool-result/output boundary lands in
#315, so the honest move at M1 is to stop advertising the record rather than to
start producing one -- producing one means running the tools, which is #315's
call to make, not this route's.

The other half is the seam. Voice built its own `HttpOpenAIProtocolLLM`
whenever LiteLLM settings were present, diverging from `build_llm_port` in the
HTTP variant, the environment variable it read, and its model-default chain.
Containment stated twice is containment that eventually differs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import services.chat_completion as service
from models.schemas import ChatCompletionRequest
from pydantic import ValidationError
from routes import chat, voice


class RecordingLLM:
    def __init__(self, content: str = "the kitchen light is on") -> None:
        self._content = content
        self.requests: list[ChatCompletionRequest] = []

    async def complete(self, req: ChatCompletionRequest) -> dict:
        self.requests.append(req)
        return {"choices": [{"message": {"role": "assistant", "content": self._content}}]}


class FakeRequest:
    def __init__(self) -> None:
        self.state = SimpleNamespace(user={"id": "user-1"})


def _utterance(**kw: str) -> voice.VoiceIntentBody:
    return voice.VoiceIntentBody(text=kw.pop("text", "turn the kitchen light on"), **kw)


class TestTheResponseSaysOnlyWhatTheRouteCanEstablish:
    def test_no_field_survives_that_the_route_cannot_fill(self) -> None:
        assert set(voice.VoiceIntentResponse.model_fields) == {"understood", "intent", "reply"}

    def test_actions_taken_is_gone_rather_than_permanently_empty(self) -> None:
        """Removed, not defaulted to `[]`.

        An always-empty list is worse than no field: a caller cannot tell "no
        tool ran" from "a tool ran and nobody recorded it", and the second is
        exactly the state #315 exists to make impossible.
        """
        assert "actions_taken" not in voice.VoiceIntentResponse.model_fields

    def test_intent_is_constrained_to_the_two_states_it_can_distinguish(self) -> None:
        with pytest.raises(ValidationError):
            voice.VoiceIntentResponse(understood=True, intent="turned_on_light", reply="done")

    @pytest.mark.asyncio
    async def test_a_reply_is_conversation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(voice, "build_llm_port", lambda: RecordingLLM())

        result = await voice.voice_intent(_utterance(room="kitchen"), FakeRequest())

        assert result.understood is True
        assert result.intent == "conversation"
        assert result.reply == "the kitchen light is on"

    @pytest.mark.asyncio
    async def test_no_reply_is_unknown_rather_than_a_silent_conversation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(voice, "build_llm_port", lambda: RecordingLLM(content=""))

        result = await voice.voice_intent(_utterance(), FakeRequest())

        assert result.understood is False
        assert result.intent == "unknown"


class TestVoiceRunsOnTheChatPathsSeam:
    def test_both_routes_pass_through_the_same_containment_helper(self) -> None:
        """Identity, not equivalence.

        Two functions that merely agree today are two places to change when the
        boundary moves, and the voice route is the one nobody looks at.
        """
        assert voice.conversation_only is service.conversation_only
        assert chat._conversation_only is service.conversation_only

    @pytest.mark.asyncio
    async def test_build_llm_port_is_the_only_port_voice_constructs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stubbing the shared builder is sufficient to keep voice offline.

        This is the regression test for the second execution path: while voice
        constructed the HTTP adapter itself, a developer `.env` carrying a
        LiteLLM base and key was enough to make this route reach the network
        even with `build_llm_port` stubbed.
        """
        import adapters.llm_http as llm_http

        # The exact condition the old branch keyed on. Without these the old
        # code fell through to `build_llm_port` too, and this test would pass
        # against the defect it exists to catch.
        monkeypatch.setenv("LITELLM_API_BASE", "https://litellm.invalid")
        monkeypatch.setenv("LITELLM_API_KEY", "not-" + "a-real-credential")

        def refuse(**_kwargs: object) -> object:
            raise AssertionError("voice must not construct its own transport")

        monkeypatch.setattr(llm_http, "HttpOpenAIProtocolLLM", refuse)
        monkeypatch.setattr(voice, "build_llm_port", lambda: RecordingLLM())

        result = await voice.voice_intent(_utterance(), FakeRequest())

        assert result.reply == "the kitchen light is on"

    @pytest.mark.asyncio
    async def test_the_utterance_reaches_the_model_with_no_tools_offered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recording = RecordingLLM()
        monkeypatch.setattr(voice, "build_llm_port", lambda: recording)

        await voice.voice_intent(
            _utterance(room="kitchen", source="satellite-1", person="sam"), FakeRequest()
        )

        sent = recording.requests[0]
        assert sent.tools is None
        assert not sent.model_extra
        prompt = sent.messages[0]["content"]
        for fragment in ("turn the kitchen light on", "kitchen", "satellite-1", "sam"):
            assert fragment in prompt
