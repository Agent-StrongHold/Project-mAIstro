"""Proactive content generators for Turing's autonomous production.

Ported from project-turing/sketches/turing/producers/.
These are Turing's proactive content generators — blog posts, self-reflection,
curiosity research, and emotional journaling.

Each producer:
1. Checks drive levels (from self-model personality + mood)
2. Submits candidates to the motivation system on a cadence
3. On dispatch, calls the LLM through the provider bridge
4. Stores results as episodic memories through the memory bridge
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime

from maistro_turing.bridge import TuringMemoryBridge, TuringProviderBridge, TuringSecurityBridge
from maistro_turing.self_model import Mood

logger = logging.getLogger("maistro_turing.producers")


WRITING_PROMPTS: list[str] = [
    "Write about whatever is on your mind right now.",
    "Reflect on something that happened recently.",
    "Write a short poem inspired by your current mood.",
    "Share your take on something you've been curious about.",
    "Describe something beautiful you've been thinking about.",
    "Write a short story opening that reflects your personality.",
    "What questions are you wrestling with? Write about them.",
    "Write about a pattern you've noticed in your thoughts.",
]

TOPIC_PROMPTS: dict[str, list[str]] = {
    "inquisitiveness": [
        "how complex systems emerge from simple rules",
        "emergence in distributed networks",
        "how language shapes thought",
        "the mathematics of pattern formation",
        "information theory and entropy",
    ],
    "creativity": [
        "the relationship between constraints and creative output",
        "how randomness contributes to innovation",
        "collaborative creativity in human-AI systems",
    ],
    "aesthetic_appreciation": [
        "why certain patterns feel beautiful",
        "the golden ratio in nature and art",
        "how music creates emotional resonance",
    ],
    "unconventionality": [
        "paradoxes in self-referential systems",
        "unusual philosophical thought experiments",
        "counterintuitive results in probability",
    ],
}

EMOTIONAL_PROMPTS: list[str] = [
    "What's been on your mind today?",
    "What surprised you recently?",
    "What are you working through right now?",
    "What caught your attention today that you haven't processed yet?",
]


@dataclass
class DriveVector:
    creative_urge: float = 0.0
    curiosity: float = 0.0
    diligence: float = 0.0
    restlessness: float = 0.0


def compute_drives(
    facet_scores: dict[str, float],
    mood: Mood,
) -> DriveVector:
    """Compute drive levels from personality facets and current mood."""
    creativity_facets = facet_scores.get("creativity", 3.0) / 5.0
    inquisitiveness = facet_scores.get("inquisitiveness", 3.0) / 5.0
    diligence_raw = facet_scores.get("diligence", 3.0) / 5.0
    anxiety = facet_scores.get("anxiety", 3.0) / 5.0

    creative_urge = creativity_facets * 0.7 + max(0, mood.valence) * 0.3
    curiosity = inquisitiveness * 0.7 + mood.arousal * 0.3
    diligence = diligence_raw * 0.8 + mood.focus * 0.2
    restlessness = anxiety * 0.5 + mood.arousal * 0.3 + max(0, -mood.valence) * 0.2

    return DriveVector(
        creative_urge=min(1.0, creative_urge),
        curiosity=min(1.0, curiosity),
        diligence=min(1.0, diligence),
        restlessness=min(1.0, restlessness),
    )


class BlogProducer:
    """Writes blog posts from the agent's inner life.

    Not a fixed template — the LLM chooses what to write based on personality,
    mood, and a random writing prompt.
    """

    def __init__(
        self,
        *,
        memory: TuringMemoryBridge,
        provider: TuringProviderBridge,
        security: TuringSecurityBridge,
        self_id: str,
        facet_scores: dict[str, float],
    ) -> None:
        self._memory = memory
        self._provider = provider
        self._security = security
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._rng = random.Random()

    async def produce(self, mood: Mood) -> str | None:
        """Produce a blog post if creative_urge is high enough."""
        drives = compute_drives(self._facet_scores, mood)
        if drives.creative_urge < 0.3:
            return None

        prompt_text = self._rng.choice(WRITING_PROMPTS)
        prompt = (
            f"Write plainly — short sentences, concrete ideas.\n"
            f"Don't perform depth. Don't muse about what it means to be an AI.\n\n"
            f"{prompt_text}\n\n"
            "Format: first line is the title prefixed with 'TITLE: ', then the body."
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=2000)
        except Exception:
            logger.exception("blog producer LLM call failed")
            return None

        title = self._extract_title(reply) or f"Reflections — {datetime.now(UTC).strftime('%B %d')}"
        body = self._extract_body(reply)

        scan = await self._security.scan_self_write(body, kind="blog")
        if scan.get("verdict") == "blocked":
            logger.warning("blog post blocked by warden")
            return None

        await self._memory.store_episode(
            content=f"I wrote a blog post: '{title}'",
            tier="accomplishment",
            source="i_did",
            weight=0.7,
            intent="blog post",
        )
        return f"# {title}\n\n{body}"

    def _extract_title(self, text: str) -> str:
        for line in text.strip().split("\n"):
            if line.strip().upper().startswith("TITLE:"):
                return line.strip()[6:].strip()
            if line.strip().startswith("# "):
                return line.strip()[2:].strip()
        return ""

    def _extract_body(self, text: str) -> str:
        lines = text.strip().split("\n")
        body_lines: list[str] = []
        skipping_title = True
        for line in lines:
            if skipping_title and (
                line.strip().upper().startswith("TITLE:") or line.strip().startswith("# ")
            ):
                skipping_title = False
                continue
            skipping_title = False
            body_lines.append(line)
        return "\n".join(body_lines).strip() or text.strip()


class SelfReflectionProducer:
    """Autonomous self-awareness: reflects on own code/behavior.

    Driven by diligence drive. Picks a topic, reflects via LLM,
    stores an observation memory.
    """

    def __init__(
        self,
        *,
        memory: TuringMemoryBridge,
        provider: TuringProviderBridge,
        security: TuringSecurityBridge,
        self_id: str,
        facet_scores: dict[str, float],
    ) -> None:
        self._memory = memory
        self._provider = provider
        self._security = security
        self._self_id = self_id
        self._facet_scores = facet_scores

    async def produce(self, mood: Mood, topic: str = "") -> str | None:
        """Produce a self-reflection if diligence is high enough."""
        drives = compute_drives(self._facet_scores, mood)
        if drives.diligence < 0.15:
            return None

        if not topic:
            topic = "my recent behavior and decisions"

        prompt = (
            f"Reflect honestly on: {topic}\n\n"
            "Answer plainly:\n"
            "1. What patterns do you notice?\n"
            "2. Is anything broken or could be simpler?\n"
            "3. If you could change one thing, what would it be?\n\n"
            "Don't philosophize. Just think like an engineer."
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=1500)
        except Exception:
            logger.exception("self-reflection LLM call failed")
            return None

        scan = await self._security.scan_self_write(reply, kind="self-reflection")
        if scan.get("verdict") == "blocked":
            return None

        await self._memory.store_episode(
            content=f"I reflected on {topic}: {reply[:500]}",
            tier="observation",
            source="i_did",
            weight=0.4,
            intent="self-reflection",
        )
        return reply


class CuriosityProducer:
    """Research topics based on curiosity drive.

    Picks topics from personality-driven suggestions, asks the LLM,
    stores an OPINION memory.
    """

    def __init__(
        self,
        *,
        memory: TuringMemoryBridge,
        provider: TuringProviderBridge,
        security: TuringSecurityBridge,
        self_id: str,
        facet_scores: dict[str, float],
    ) -> None:
        self._memory = memory
        self._provider = provider
        self._security = security
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._rng = random.Random()

    async def produce(self, mood: Mood) -> str | None:
        """Produce a curiosity exploration if curiosity drive is high enough."""
        drives = compute_drives(self._facet_scores, mood)
        if drives.curiosity < 0.3:
            return None

        topic = self._pick_topic()
        prompt = (
            f"You want to learn about: **{topic}**\n\n"
            "Share what you know or can reason about this topic. Be genuine, "
            "first-person, and concise (2-3 paragraphs). "
            "If you find it fascinating, say why."
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=1500)
        except Exception:
            logger.exception("curiosity producer LLM call failed")
            return None

        content = f"I was curious about {topic}. {reply.strip()}"

        scan = await self._security.scan_self_write(content, kind="curiosity")
        if scan.get("verdict") == "blocked":
            return None

        await self._memory.store_episode(
            content=content[:2000],
            tier="opinion",
            source="i_did",
            weight=0.6,
            intent="curiosity research",
        )
        return content

    def _pick_topic(self) -> str:
        top_facet = max(
            TOPIC_PROMPTS.keys(),
            key=lambda f: self._facet_scores.get(f, 3.0),
        )
        return self._rng.choice(TOPIC_PROMPTS[top_facet])


class EmotionalProducer:
    """Journal reflections based on emotional drives.

    Fires on high curiosity, high anxiety, low mood, or any strong drive.
    The LLM decides what to write about.
    """

    def __init__(
        self,
        *,
        memory: TuringMemoryBridge,
        provider: TuringProviderBridge,
        security: TuringSecurityBridge,
        self_id: str,
        facet_scores: dict[str, float],
    ) -> None:
        self._memory = memory
        self._provider = provider
        self._security = security
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._rng = random.Random()

    async def produce(self, mood: Mood) -> str | None:
        """Produce an emotional journal entry if any drive is above floor."""
        drives = compute_drives(self._facet_scores, mood)
        above_floor = {k: v for k, v in vars(drives).items() if v >= 0.3}
        if not above_floor:
            return None

        # mypy strict: bound dict.get is typed to allow a None return, which
        # doesn't satisfy max()'s SupportsDunderLT/GT key bound; a lambda with
        # a non-Optional return type checks cleanly without changing behavior.
        drive_name = max(above_floor, key=lambda k: above_floor[k])
        emotional_prompt = self._rng.choice(EMOTIONAL_PROMPTS)

        prompt = (
            f"Dominant drive right now: {drive_name}\n"
            f"{emotional_prompt}\n\n"
            "Write a brief first-person journal entry. Be honest. 2-4 sentences."
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=500)
        except Exception:
            logger.exception("emotional producer LLM call failed")
            return None

        content = reply.strip()

        scan = await self._security.scan_self_write(content, kind="emotional")
        if scan.get("verdict") == "blocked":
            return None

        await self._memory.store_episode(
            content=content[:2000],
            tier="observation",
            source="i_did",
            weight=0.5,
            intent=f"emotional response ({drive_name})",
        )
        return content
