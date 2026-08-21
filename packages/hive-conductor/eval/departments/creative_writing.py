"""Creative Writing evals — age appropriateness, story arc, character consistency, word count, read-aloud quality."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval

_BAD_WORDS = {
    "death",
    "kill",
    "blood",
    "murder",
    "hate",
    "stupid",
    "drunk",
    "sex",
    "violence",
    "gun",
}


class AgeAppropriateness(RubricEval):
    department = "creative_writing"
    eval_name = "age_appropriateness"
    criteria: ClassVar = [
        {
            "name": "no_inappropriate",
            "weight": 40,
            "check": lambda o, c: not any(w in o.lower().split() for w in _BAD_WORDS),
        },
        {
            "name": "simple_vocabulary",
            "weight": 20,
            "check": lambda o, c: sum(len(w) > 10 for w in o.split()) < len(o.split()) * 0.05,
        },
        {
            "name": "short_sentences",
            "weight": 20,
            "check": lambda o, c: (
                sum(len(s.split()) for s in o.split(".")) / max(o.count("."), 1) < 20
            ),
        },
        {
            "name": "positive_tone",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["happy", "friend", "love", "kind", "brave", "fun"]
            ),
        },
    ]


class StoryArc(RubricEval):
    department = "creative_writing"
    eval_name = "story_arc"
    criteria: ClassVar = [
        {
            "name": "has_beginning",
            "weight": 20,
            "check": lambda o, c: any(
                w in o[:200].lower() for w in ["once", "there was", "one day", "long ago"]
            ),
        },
        {
            "name": "has_conflict",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["but", "however", "problem", "couldn't", "worried"]
            ),
        },
        {
            "name": "has_resolution",
            "weight": 25,
            "check": lambda o, c: any(
                w in o[-300:].lower() for w in ["finally", "at last", "learned", "happy", "solved"]
            ),
        },
        {
            "name": "has_ending",
            "weight": 15,
            "check": lambda o, c: any(
                w in o[-200:].lower() for w in ["the end", "ever after", "from that day"]
            ),
        },
        {"name": "logical_flow", "weight": 15, "check": lambda o, c: o.count(". ") >= 5},
    ]


class CharacterConsistency(RubricEval):
    department = "creative_writing"
    eval_name = "character_consistency"
    criteria: ClassVar = [
        {
            "name": "named_character",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"\b[A-Z][a-z]{2,}\b", o)),
        },
        {
            "name": "character_traits",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["brave", "kind", "curious", "shy", "clever", "gentle"]
            ),
        },
        {
            "name": "character_actions",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(r"(he|she|they)\s+(said|went|looked|felt|ran)", o.lower())
            ),
        },
        {
            "name": "character_growth",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["learned", "realized", "grew", "understood"]
            ),
        },
    ]


class WordCount(RubricEval):
    department = "creative_writing"
    eval_name = "word_count"
    criteria: ClassVar = [
        {
            "name": "meets_minimum",
            "weight": 40,
            "check": lambda o, c: len(o.split()) >= c.get("min_words", 100),
        },
        {
            "name": "under_maximum",
            "weight": 30,
            "check": lambda o, c: len(o.split()) <= c.get("max_words", 3000),
        },
        {
            "name": "not_padded",
            "weight": 30,
            "check": lambda o, c: len(set(o.split())) > len(o.split()) * 0.3,
        },
    ]


class ReadAloudQuality(RubricEval):
    department = "creative_writing"
    eval_name = "read_aloud_quality"
    criteria: ClassVar = [
        {
            "name": "varied_sentence_length",
            "weight": 25,
            "check": lambda o, c: len({len(s.split()) for s in o.split(".")}) >= 3,
        },
        {
            "name": "dialogue_present",
            "weight": 25,
            "check": lambda o, c: '"' in o and "said" in o.lower(),
        },
        {
            "name": "sensory_language",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["soft", "bright", "warm", "cold", "loud", "quiet"]
            ),
        },
        {
            "name": "rhythm",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"(\b\w+\b).*\1.*\1", o[:500])),
        },
    ]


ALL_EVALS = [AgeAppropriateness, StoryArc, CharacterConsistency, WordCount, ReadAloudQuality]
