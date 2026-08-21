"""Finance evals — numerical accuracy, regulatory compliance, risk identification, assumption transparency, decision clarity."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval


class NumericalAccuracy(RubricEval):
    department = "finance"
    eval_name = "numerical_accuracy"
    criteria: ClassVar = [
        {
            "name": "has_numbers",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"\$[\d,.]+|\d+%|\d+\.\d+", o)),
        },
        {
            "name": "numbers_add_up",
            "weight": 25,
            "check": lambda o, c: "total" in o.lower() or "sum" in o.lower() or "net" in o.lower(),
        },
        {
            "name": "units_specified",
            "weight": 25,
            "check": lambda o, c: any(
                w in o for w in ["$", "%", "USD", "EUR", "bps", "M", "B", "K"]
            ),
        },
        {
            "name": "precision_appropriate",
            "weight": 25,
            "check": lambda o, c: bool(re.search(r"\d+\.\d{1,2}[^0-9]", o)),
        },
    ]


class RegulatoryCompliance(RubricEval):
    department = "finance"
    eval_name = "regulatory_compliance"
    criteria: ClassVar = [
        {
            "name": "mentions_regulations",
            "weight": 25,
            "check": lambda o, c: any(
                w in o for w in ["GAAP", "IFRS", "SEC", "SOX", "FASB", "IRS", "compliance"]
            ),
        },
        {
            "name": "disclaimers",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["disclaimer", "not financial advice", "consult", "subject to"]
            ),
        },
        {
            "name": "audit_trail",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["source", "reference", "as of", "period ending"]
            ),
        },
        {
            "name": "materiality",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["material", "significant", "threshold", "de minimis"]
            ),
        },
    ]


class RiskIdentification(RubricEval):
    department = "finance"
    eval_name = "risk_identification"
    criteria: ClassVar = [
        {
            "name": "identifies_risks",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["risk", "exposure", "downside", "threat", "vulnerability"]
            ),
        },
        {
            "name": "quantifies_impact",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(r"(risk|impact|loss).*\d+|\d+.*(risk|impact|loss)", o.lower())
            ),
        },
        {
            "name": "mitigation_strategies",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["mitigat", "hedge", "diversif", "contingency", "insurance"]
            ),
        },
        {
            "name": "probability_assessment",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["likely", "probability", "scenario", "best case", "worst case"]
            ),
        },
    ]


class AssumptionTransparency(RubricEval):
    department = "finance"
    eval_name = "assumption_transparency"
    criteria: ClassVar = [
        {
            "name": "states_assumptions",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower() for w in ["assumption", "assumes", "assuming", "based on"]
            ),
        },
        {
            "name": "sensitivity_analysis",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["sensitivity", "if", "scenario", "range", "varies"]
            ),
        },
        {
            "name": "data_sources",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["source", "data from", "based on", "as reported"]
            ),
        },
        {
            "name": "limitations_noted",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["limitation", "caveat", "note that", "important to"]
            ),
        },
    ]


class DecisionClarity(RubricEval):
    department = "finance"
    eval_name = "decision_clarity"
    criteria: ClassVar = [
        {
            "name": "clear_recommendation",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower() for w in ["recommend", "suggest", "advise", "conclusion", "decision"]
            ),
        },
        {
            "name": "options_compared",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["option", "alternative", "versus", "compared to", "vs"]
            ),
        },
        {
            "name": "criteria_stated",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["criteria", "metric", "kpi", "measure", "benchmark"]
            ),
        },
        {
            "name": "next_steps",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["next step", "action", "proceed", "implement", "timeline"]
            ),
        },
    ]


ALL_EVALS = [
    NumericalAccuracy,
    RegulatoryCompliance,
    RiskIdentification,
    AssumptionTransparency,
    DecisionClarity,
]
