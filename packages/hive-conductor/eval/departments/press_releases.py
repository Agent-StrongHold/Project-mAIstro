"""Press Releases evals — inverted pyramid, quote quality, factual accuracy, AP style, newsworthiness."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval


class InvertedPyramid(RubricEval):
    department = "press_releases"
    eval_name = "inverted_pyramid"
    criteria: ClassVar = [
        {
            "name": "lead_has_who_what",
            "weight": 25,
            "check": lambda o, c: any(
                w in o[:200].lower() for w in ["announced", "launched", "released", "appointed"]
            ),
        },
        {
            "name": "lead_has_when_where",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(r"(today|yesterday|\d{4}|January|February|March)", o[:300])
            ),
        },
        {"name": "details_follow", "weight": 25, "check": lambda o, c: len(o.split("\n\n")) >= 3},
        {
            "name": "background_last",
            "weight": 25,
            "check": lambda o, c: any(
                w in o[-500:].lower() for w in ["about", "founded", "headquartered", "contact"]
            ),
        },
    ]


class QuoteQuality(RubricEval):
    department = "press_releases"
    eval_name = "quote_quality"
    criteria: ClassVar = [
        {"name": "has_quotes", "weight": 30, "check": lambda o, c: o.count('"') >= 4},
        {
            "name": "attributed",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["said", "stated", "commented", "noted"]
            ),
        },
        {
            "name": "titled_speaker",
            "weight": 25,
            "check": lambda o, c: any(
                w in o for w in ["CEO", "President", "Director", "VP", "Chief"]
            ),
        },
        {
            "name": "adds_value",
            "weight": 20,
            "check": lambda o, c: len(re.findall(r'"[^"]{30,}"', o)) >= 1,
        },
    ]


class FactualAccuracy(RubricEval):
    department = "press_releases"
    eval_name = "factual_accuracy"
    criteria: ClassVar = [
        {
            "name": "specific_numbers",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"\$[\d,.]+|\d+%|\d+,\d{3}", o)),
        },
        {
            "name": "verifiable_claims",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["according to", "based on", "data shows"]
            ),
        },
        {
            "name": "no_unproven_superlatives",
            "weight": 25,
            "check": lambda o, c: (
                not any(w in o.lower() for w in ["best in class", "world's first", "revolutionary"])
            ),
        },
        {
            "name": "date_present",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(
                    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d",
                    o,
                )
            ),
        },
    ]


class APStyle(RubricEval):
    department = "press_releases"
    eval_name = "ap_style"
    criteria: ClassVar = [
        {
            "name": "dateline",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"^[A-Z]{2,}[\s,]", o)),
        },
        {"name": "no_exclamation_marks", "weight": 25, "check": lambda o, c: o.count("!") == 0},
        {"name": "third_person", "weight": 25, "check": lambda o, c: "we " not in o.lower()[:500]},
        {
            "name": "boilerplate",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["about ", "###", "media contact", "for immediate release"]
            ),
        },
    ]


class Newsworthiness(RubricEval):
    department = "press_releases"
    eval_name = "newsworthiness"
    criteria: ClassVar = [
        {
            "name": "timeliness",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["today", "announces", "new", "launch"]
            ),
        },
        {
            "name": "impact",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["million", "billion", "thousands", "industry", "market"]
            ),
        },
        {
            "name": "prominence",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"[A-Z][a-z]+\s[A-Z][a-z]+", o[:500])),
        },
        {
            "name": "relevance",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["solution", "problem", "challenge", "opportunity"]
            ),
        },
    ]


ALL_EVALS = [InvertedPyramid, QuoteQuality, FactualAccuracy, APStyle, Newsworthiness]
