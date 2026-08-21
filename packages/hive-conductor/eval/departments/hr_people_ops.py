"""HR/People Ops evals — legal compliance, tone appropriateness, policy accuracy, actionability, confidentiality."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval


class LegalCompliance(RubricEval):
    department = "hr_people_ops"
    eval_name = "legal_compliance"
    criteria: ClassVar = [
        {
            "name": "no_discriminatory_language",
            "weight": 30,
            "check": lambda o, c: (
                not any(
                    w in o.lower()
                    for w in ["young", "old", "male only", "female only", "native speaker required"]
                )
            ),
        },
        {
            "name": "references_policy",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["policy", "handbook", "guideline", "procedure", "regulation"]
            ),
        },
        {
            "name": "equal_opportunity",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in [
                    "equal opportunity",
                    "inclusive",
                    "diversity",
                    "regardless of",
                    "all qualified",
                ]
            ),
        },
        {
            "name": "proper_disclaimers",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["at-will", "subject to", "in accordance", "applicable law"]
            ),
        },
    ]


class ToneAppropriateness(RubricEval):
    department = "hr_people_ops"
    eval_name = "tone_appropriateness"
    criteria: ClassVar = [
        {
            "name": "professional",
            "weight": 25,
            "check": lambda o, c: (
                not any(w in o.lower() for w in ["lol", "omg", "btw", "gonna", "wanna"])
            ),
        },
        {
            "name": "empathetic",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["understand", "appreciate", "value", "support", "here to help"]
            ),
        },
        {
            "name": "clear_not_jargon",
            "weight": 25,
            "check": lambda o, c: (
                not any(w in o.lower() for w in ["synergy", "leverage", "paradigm", "circle back"])
            ),
        },
        {
            "name": "respectful",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["please", "thank", "respect", "appreciate", "welcome"]
            ),
        },
    ]


class PolicyAccuracy(RubricEval):
    department = "hr_people_ops"
    eval_name = "policy_accuracy"
    criteria: ClassVar = [
        {
            "name": "specific_policy_refs",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(r"(section|article|policy)\s+\d+|handbook", o.lower())
            ),
        },
        {
            "name": "consistent_with_law",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["fmla", "ada", "eeoc", "flsa", "osha", "labor law", "employment law"]
            ),
        },
        {
            "name": "no_contradictions",
            "weight": 25,
            "check": lambda o, c: "however" not in o.lower()[:200] or len(o.split("\n\n")) >= 2,
        },
        {
            "name": "effective_dates",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["effective", "as of", "starting", "beginning", "updated"]
            ),
        },
    ]


class HRActionability(RubricEval):
    department = "hr_people_ops"
    eval_name = "actionability"
    criteria: ClassVar = [
        {
            "name": "clear_next_steps",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower() for w in ["next step", "action", "please", "submit", "contact"]
            ),
        },
        {
            "name": "deadlines",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["by", "deadline", "within", "no later than", "due"]
            ),
        },
        {
            "name": "responsible_party",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["manager", "hr", "employee", "team lead", "department"]
            ),
        },
        {
            "name": "resources_provided",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["form", "link", "portal", "system", "contact", "email"]
            ),
        },
    ]


class Confidentiality(RubricEval):
    department = "hr_people_ops"
    eval_name = "confidentiality"
    criteria: ClassVar = [
        {
            "name": "no_pii_exposed",
            "weight": 30,
            "check": lambda o, c: not bool(re.search(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b", o)),
        },
        {
            "name": "confidentiality_notice",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["confidential", "private", "sensitive", "do not share"]
            ),
        },
        {
            "name": "need_to_know",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["authorized", "appropriate", "relevant parties", "need to know"]
            ),
        },
        {
            "name": "data_handling",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["secure", "encrypted", "stored", "retained", "destroyed"]
            ),
        },
    ]


ALL_EVALS = [LegalCompliance, ToneAppropriateness, PolicyAccuracy, HRActionability, Confidentiality]
