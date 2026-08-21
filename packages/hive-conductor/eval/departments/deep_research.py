"""Deep Research evals — source attribution, claim factuality, completeness, synthesis, actionability."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval


class SourceAttribution(RubricEval):
    department = "deep_research"
    eval_name = "source_attribution"
    criteria: ClassVar = [
        {
            "name": "has_citations",
            "weight": 30,
            "check": lambda o, c: bool(re.search(r"\[\d+\]|\(\d{4}\)|https?://|Source:", o)),
        },
        {
            "name": "min_3_sources",
            "weight": 25,
            "check": lambda o, c: len(re.findall(r"\[\d+\]|Source:|https?://\S+", o)) >= 3,
        },
        {
            "name": "inline_attribution",
            "weight": 25,
            "check": lambda o, c: "according to" in o.lower() or "per " in o.lower(),
        },
        {
            "name": "no_unsupported_claims",
            "weight": 20,
            "check": lambda o, c: "studies show" not in o.lower() or bool(re.search(r"\[\d+\]", o)),
        },
    ]


class ClaimFactuality(RubricEval):
    department = "deep_research"
    eval_name = "claim_factuality"
    criteria: ClassVar = [
        {
            "name": "hedges_uncertainty",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["may", "likely", "suggests", "indicates"]
            ),
        },
        {
            "name": "no_absolute_claims",
            "weight": 25,
            "check": lambda o, c: (
                not any(w in o.lower() for w in ["always", "never", "impossible", "guaranteed"])
            ),
        },
        {
            "name": "quantified_claims",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"\d+%|\d+\.\d+", o)),
        },
        {
            "name": "distinguishes_fact_opinion",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["evidence", "data", "research", "analysis"]
            ),
        },
    ]


class Completeness(RubricEval):
    department = "deep_research"
    eval_name = "completeness"
    criteria: ClassVar = [
        {
            "name": "has_sections",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"#{1,3}\s|^\d+\.", o, re.MULTILINE)),
        },
        {
            "name": "has_conclusion",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()[-500:] for w in ["conclusion", "summary", "key takeaway"]
            ),
        },
        {"name": "min_length", "weight": 25, "check": lambda o, c: len(o.split()) >= 300},
        {
            "name": "covers_multiple_angles",
            "weight": 25,
            "check": lambda o, c: len(re.findall(r"#{1,3}\s|^\d+\.", o, re.MULTILINE)) >= 3,
        },
    ]


class Synthesis(RubricEval):
    department = "deep_research"
    eval_name = "synthesis"
    criteria: ClassVar = [
        {
            "name": "connects_sources",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower() for w in ["similarly", "in contrast", "building on", "corroborates"]
            ),
        },
        {
            "name": "identifies_patterns",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["pattern", "trend", "theme", "recurring"]
            ),
        },
        {
            "name": "novel_insight",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["implication", "suggests that", "therefore", "consequently"]
            ),
        },
        {
            "name": "not_just_list",
            "weight": 20,
            "check": lambda o, c: o.count("- ") < len(o.split("\n")) * 0.7,
        },
    ]


class Actionability(RubricEval):
    department = "deep_research"
    eval_name = "actionability"
    criteria: ClassVar = [
        {
            "name": "has_recommendations",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower() for w in ["recommend", "should", "next step", "action item"]
            ),
        },
        {
            "name": "specific_not_vague",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"\d+|specific|concrete", o.lower())),
        },
        {
            "name": "prioritized",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["first", "priority", "most important", "critical"]
            ),
        },
        {
            "name": "feasible",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["timeline", "resource", "budget", "team"]
            ),
        },
    ]


ALL_EVALS = [SourceAttribution, ClaimFactuality, Completeness, Synthesis, Actionability]
