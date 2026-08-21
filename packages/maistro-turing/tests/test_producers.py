"""Tests for producers.py: drive computation and proactive content producers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro_turing.producers import (
    EMOTIONAL_PROMPTS,
    TOPIC_PROMPTS,
    WRITING_PROMPTS,
    BlogProducer,
    CuriosityProducer,
    DriveVector,
    EmotionalProducer,
    SelfReflectionProducer,
    compute_drives,
)
from maistro_turing.self_model import Mood


def _mood(valence: float = 0.0, arousal: float = 0.0, focus: float = 0.0) -> Mood:
    return Mood(
        self_id="self-1",
        valence=valence,
        arousal=arousal,
        focus=focus,
        last_tick_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------- fakes ------


class FakeMemoryBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def store_episode(self, *, content: str, tier: str, **kwargs: Any) -> str:
        self.calls.append({"content": content, "tier": tier, **kwargs})
        return "mem-id"


class FakeProviderBridge:
    def __init__(self, reply: str = "a reply", raises: Exception | None = None) -> None:
        self._reply = reply
        self._raises = raises
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, max_tokens: int | None = None, pool: str = "") -> str:
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        return self._reply


class FakeSecurityBridge:
    def __init__(self, verdict: str = "allowed") -> None:
        self._verdict = verdict
        self.calls: list[tuple[str, str]] = []

    async def scan_self_write(self, content: str, *, kind: str = "") -> dict[str, Any]:
        self.calls.append((content, kind))
        return {"verdict": self._verdict, "flags": []}


# --------------------------------------------------------------- compute_drives


class TestComputeDrives:
    def test_default_facet_scores_use_midpoint(self) -> None:
        drives = compute_drives({}, _mood())
        # creativity=3/5=0.6, inquisitiveness=3/5=0.6, diligence=3/5=0.6, anxiety=3/5=0.6
        assert drives.creative_urge == pytest.approx(0.6 * 0.7)
        assert drives.curiosity == pytest.approx(0.6 * 0.7)
        assert drives.diligence == pytest.approx(0.6 * 0.8)
        assert drives.restlessness == pytest.approx(0.6 * 0.5)

    def test_positive_valence_boosts_creative_urge(self) -> None:
        drives = compute_drives({"creativity": 5.0}, _mood(valence=1.0))
        assert drives.creative_urge == pytest.approx(min(1.0, 1.0 * 0.7 + 1.0 * 0.3))

    def test_negative_valence_does_not_boost_creative_urge(self) -> None:
        drives = compute_drives({"creativity": 5.0}, _mood(valence=-1.0))
        # max(0, mood.valence) clamps negative valence to 0 contribution
        assert drives.creative_urge == pytest.approx(1.0 * 0.7)

    def test_negative_valence_boosts_restlessness(self) -> None:
        drives = compute_drives({"anxiety": 5.0}, _mood(valence=-1.0, arousal=0.0))
        assert drives.restlessness == pytest.approx(1.0 * 0.5 + 0.0 * 0.3 + 1.0 * 0.2)

    def test_positive_valence_does_not_boost_restlessness(self) -> None:
        drives = compute_drives({"anxiety": 5.0}, _mood(valence=1.0, arousal=0.0))
        # max(0, -mood.valence) clamps positive valence to 0 contribution
        assert drives.restlessness == pytest.approx(1.0 * 0.5)

    def test_all_drives_clamped_to_one(self) -> None:
        drives = compute_drives(
            {"creativity": 5.0, "inquisitiveness": 5.0, "diligence": 5.0, "anxiety": 5.0},
            _mood(valence=1.0, arousal=1.0, focus=1.0),
        )
        assert drives.creative_urge == 1.0
        assert drives.curiosity == 1.0
        assert drives.diligence == 1.0
        # restlessness = anxiety*0.5 + arousal*0.3 + max(0, -valence)*0.2;
        # with valence=1.0 the negative-valence term is clamped to 0, so this
        # stays below the 1.0 ceiling at 0.8 rather than saturating.
        assert drives.restlessness == pytest.approx(0.8)

    def test_restlessness_clamped_to_one_with_negative_valence(self) -> None:
        drives = compute_drives(
            {"anxiety": 5.0},
            _mood(valence=-1.0, arousal=1.0, focus=0.0),
        )
        # 1.0*0.5 + 1.0*0.3 + 1.0*0.2 = 1.0 exactly, exercising the min(1.0, ...) clamp.
        assert drives.restlessness == 1.0

    def test_arousal_contributes_to_curiosity(self) -> None:
        drives = compute_drives({"inquisitiveness": 0.0}, _mood(arousal=1.0))
        assert drives.curiosity == pytest.approx(0.0 * 0.7 + 1.0 * 0.3)

    def test_focus_contributes_to_diligence(self) -> None:
        drives = compute_drives({"diligence": 0.0}, _mood(focus=1.0))
        assert drives.diligence == pytest.approx(0.0 * 0.8 + 1.0 * 0.2)


def test_drive_vector_defaults() -> None:
    dv = DriveVector()
    assert dv.creative_urge == 0.0
    assert dv.curiosity == 0.0
    assert dv.diligence == 0.0
    assert dv.restlessness == 0.0


# ------------------------------------------------------------- BlogProducer


class TestBlogProducer:
    async def test_produce_returns_none_when_creative_urge_too_low(self) -> None:
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 0.0},
        )
        # creative_urge = 0*0.7 + max(0, valence)*0.3, with valence=0 -> 0.0 < 0.3
        result = await producer.produce(_mood(valence=0.0))
        assert result is None

    async def test_produce_returns_formatted_post_when_creative_urge_high(self) -> None:
        provider = FakeProviderBridge(reply="TITLE: My Day\nLine one.\nLine two.")
        memory = FakeMemoryBridge()
        security = FakeSecurityBridge()
        producer = BlogProducer(
            memory=memory,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=security,  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result == "# My Day\n\nLine one.\nLine two."
        assert memory.calls[0]["tier"] == "accomplishment"
        assert memory.calls[0]["weight"] == 0.7
        assert "I wrote a blog post: 'My Day'" in memory.calls[0]["content"]

    async def test_produce_falls_back_to_default_title_when_none_extracted(self) -> None:
        provider = FakeProviderBridge(reply="No title markers here, just body text.")
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result is not None
        assert result.startswith("# Reflections — ")

    async def test_produce_extracts_title_from_markdown_heading(self) -> None:
        provider = FakeProviderBridge(reply="# Heading Title\nBody text here.")
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result == "# Heading Title\n\nBody text here."

    async def test_produce_returns_none_when_llm_raises(self) -> None:
        provider = FakeProviderBridge(raises=RuntimeError("boom"))
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result is None

    async def test_produce_returns_none_when_blocked_by_warden(self) -> None:
        provider = FakeProviderBridge(reply="TITLE: Bad\nBad content.")
        security = FakeSecurityBridge(verdict="blocked")
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=security,  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result is None

    def test_writing_prompts_nonempty(self) -> None:
        assert len(WRITING_PROMPTS) > 0
        assert all(isinstance(p, str) for p in WRITING_PROMPTS)

    def test_extract_title_lowercase_title_marker(self) -> None:
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={},
        )
        assert producer._extract_title("title: lowercase works\nbody") == "lowercase works"

    def test_extract_body_strips_title_line_only_once(self) -> None:
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={},
        )
        body = producer._extract_body("TITLE: X\nline1\nline2")
        assert body == "line1\nline2"

    def test_extract_body_with_no_title_returns_full_text(self) -> None:
        producer = BlogProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={},
        )
        assert producer._extract_body("just body text") == "just body text"


# ------------------------------------------------------- SelfReflectionProducer


class TestSelfReflectionProducer:
    async def test_produce_returns_none_when_diligence_too_low(self) -> None:
        producer = SelfReflectionProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"diligence": 0.0},
        )
        result = await producer.produce(_mood(focus=0.0))
        assert result is None

    async def test_produce_returns_reflection_with_default_topic(self) -> None:
        provider = FakeProviderBridge(reply="Here's my reflection.")
        memory = FakeMemoryBridge()
        producer = SelfReflectionProducer(
            memory=memory,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"diligence": 5.0},
        )
        result = await producer.produce(_mood(focus=1.0))
        assert result == "Here's my reflection."
        assert "my recent behavior and decisions" in provider.prompts[0]
        assert memory.calls[0]["tier"] == "observation"
        assert memory.calls[0]["weight"] == 0.4

    async def test_produce_uses_given_topic(self) -> None:
        provider = FakeProviderBridge(reply="On topic.")
        producer = SelfReflectionProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"diligence": 5.0},
        )
        result = await producer.produce(_mood(focus=1.0), topic="my error handling")
        assert result == "On topic."
        assert "my error handling" in provider.prompts[0]

    async def test_produce_returns_none_when_llm_raises(self) -> None:
        producer = SelfReflectionProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(raises=RuntimeError("fail")),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"diligence": 5.0},
        )
        result = await producer.produce(_mood(focus=1.0))
        assert result is None

    async def test_produce_returns_none_when_blocked(self) -> None:
        producer = SelfReflectionProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(reply="reflection"),  # type: ignore[arg-type]
            security=FakeSecurityBridge(verdict="blocked"),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"diligence": 5.0},
        )
        result = await producer.produce(_mood(focus=1.0))
        assert result is None


# ----------------------------------------------------------- CuriosityProducer


class TestCuriosityProducer:
    async def test_produce_returns_none_when_curiosity_too_low(self) -> None:
        producer = CuriosityProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"inquisitiveness": 0.0},
        )
        result = await producer.produce(_mood(arousal=0.0))
        assert result is None

    async def test_produce_returns_content_and_picks_topic_from_top_facet(self) -> None:
        provider = FakeProviderBridge(reply="It's fascinating because of X.")
        memory = FakeMemoryBridge()
        producer = CuriosityProducer(
            memory=memory,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"inquisitiveness": 5.0, "creativity": 0.0},
        )
        result = await producer.produce(_mood(arousal=1.0))
        assert result is not None
        assert result.startswith("I was curious about")
        assert any(topic in result for topic in TOPIC_PROMPTS["inquisitiveness"])
        assert memory.calls[0]["tier"] == "opinion"
        assert memory.calls[0]["weight"] == 0.6

    async def test_produce_returns_none_when_llm_raises(self) -> None:
        producer = CuriosityProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(raises=RuntimeError("fail")),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"inquisitiveness": 5.0},
        )
        result = await producer.produce(_mood(arousal=1.0))
        assert result is None

    async def test_produce_returns_none_when_blocked(self) -> None:
        producer = CuriosityProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(reply="content"),  # type: ignore[arg-type]
            security=FakeSecurityBridge(verdict="blocked"),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"inquisitiveness": 5.0},
        )
        result = await producer.produce(_mood(arousal=1.0))
        assert result is None

    def test_pick_topic_defaults_to_first_facet_when_scores_tied(self) -> None:
        producer = CuriosityProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={},
        )
        topic = producer._pick_topic()
        assert topic in TOPIC_PROMPTS["inquisitiveness"]


# ----------------------------------------------------------- EmotionalProducer


class TestEmotionalProducer:
    async def test_produce_returns_none_when_no_drive_above_floor(self) -> None:
        producer = EmotionalProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={
                "creativity": 0.0,
                "inquisitiveness": 0.0,
                "diligence": 0.0,
                "anxiety": 0.0,
            },
        )
        result = await producer.produce(_mood())
        assert result is None

    async def test_produce_returns_content_when_a_drive_is_above_floor(self) -> None:
        provider = FakeProviderBridge(reply="Today was interesting.")
        memory = FakeMemoryBridge()
        producer = EmotionalProducer(
            memory=memory,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result == "Today was interesting."
        assert memory.calls[0]["tier"] == "observation"
        assert memory.calls[0]["weight"] == 0.5
        assert "creative_urge" in memory.calls[0]["intent"]

    async def test_produce_returns_none_when_llm_raises(self) -> None:
        producer = EmotionalProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(raises=RuntimeError("fail")),  # type: ignore[arg-type]
            security=FakeSecurityBridge(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result is None

    async def test_produce_returns_none_when_blocked(self) -> None:
        producer = EmotionalProducer(
            memory=FakeMemoryBridge(),  # type: ignore[arg-type]
            provider=FakeProviderBridge(reply="content"),  # type: ignore[arg-type]
            security=FakeSecurityBridge(verdict="blocked"),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood(valence=1.0))
        assert result is None

    def test_emotional_prompts_nonempty(self) -> None:
        assert len(EMOTIONAL_PROMPTS) > 0
