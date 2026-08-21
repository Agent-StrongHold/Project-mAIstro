"""Legal evals — clause completeness, ambiguity score, risk exposure, jurisdiction, plain language."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval


class ClauseCompleteness(RubricEval):
    department = "legal"
    eval_name = "clause_completeness"
    criteria: ClassVar = [
        {
            "name": "has_definitions",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["defined as", "means", "herein", "definition", '"']
            ),
        },
        {
            "name": "has_obligations",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["shall", "must", "obligat", "required to", "agrees to"]
            ),
        },
        {
            "name": "has_termination",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["terminat", "expir", "cancel", "end of term"]
            ),
        },
        {
            "name": "has_liability",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["liability", "indemnif", "damages", "limitation of"]
            ),
        },
        {
            "name": "has_governing_law",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["governing law", "jurisdiction", "venue", "governed by"]
            ),
        },
    ]


class AmbiguityScore(RubricEval):
    department = "legal"
    eval_name = "ambiguity_score"
    criteria: ClassVar = [
        {
            "name": "no_vague_terms",
            "weight": 25,
            "check": lambda o, c: (
                not any(
                    w in o.lower()
                    for w in [
                        "reasonable efforts",
                        "as appropriate",
                        "from time to time",
                        "as needed",
                    ]
                )
            ),
        },
        {
            "name": "defined_terms_used",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r'"[A-Z][^"]+"|[A-Z][a-z]+(?:\s[A-Z][a-z]+)+', o)),
        },
        {
            "name": "specific_timeframes",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(r"\d+\s*(days?|months?|years?|business days?)", o)
            ),
        },
        {
            "name": "clear_conditions",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["if", "provided that", "subject to", "unless", "except"]
            ),
        },
    ]


class RiskExposure(RubricEval):
    department = "legal"
    eval_name = "risk_exposure"
    criteria: ClassVar = [
        {
            "name": "identifies_risks",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["risk", "exposure", "liability", "breach", "default"]
            ),
        },
        {
            "name": "caps_damages",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["limitation", "cap", "not exceed", "maximum", "aggregate"]
            ),
        },
        {"name": "indemnification", "weight": 25, "check": lambda o, c: "indemnif" in o.lower()},
        {
            "name": "insurance_requirements",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["insurance", "coverage", "policy", "certificate"]
            ),
        },
    ]


class Jurisdiction(RubricEval):
    department = "legal"
    eval_name = "jurisdiction"
    criteria: ClassVar = [
        {
            "name": "specifies_jurisdiction",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower() for w in ["state of", "county of", "district of", "courts of"]
            ),
        },
        {
            "name": "choice_of_law",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["governed by", "laws of", "choice of law", "applicable law"]
            ),
        },
        {
            "name": "dispute_resolution",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["arbitration", "mediation", "dispute", "resolution", "litigation"]
            ),
        },
        {
            "name": "venue",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["venue", "forum", "exclusive jurisdiction", "submit to"]
            ),
        },
    ]


class PlainLanguage(RubricEval):
    department = "legal"
    eval_name = "plain_language"
    criteria: ClassVar = [
        {
            "name": "short_sentences",
            "weight": 25,
            "check": lambda o, c: (
                sum(len(s.split()) for s in o.split(".")) / max(o.count("."), 1) < 30
            ),
        },
        {
            "name": "active_voice",
            "weight": 25,
            "check": lambda o, c: o.lower().count("shall be") < o.lower().count("will") + 1,
        },
        {
            "name": "minimal_latin",
            "weight": 25,
            "check": lambda o, c: (
                sum(
                    1
                    for w in ["inter alia", "mutatis mutandis", "ipso facto", "prima facie"]
                    if w in o.lower()
                )
                < 2
            ),
        },
        {
            "name": "headers_used",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(r"#{1,3}\s|^\d+\.\s|^[A-Z][A-Z\s]+$", o, re.MULTILINE)
            ),
        },
    ]


ALL_EVALS = [ClauseCompleteness, AmbiguityScore, RiskExposure, Jurisdiction, PlainLanguage]
