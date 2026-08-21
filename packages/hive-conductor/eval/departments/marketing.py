"""Marketing evals — brand voice, CTA clarity, audience targeting, channel fit, measurability."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval


class BrandVoice(RubricEval):
    department = "marketing"
    eval_name = "brand_voice"
    criteria: ClassVar = [
        {
            "name": "consistent_tone",
            "weight": 25,
            "check": lambda o, c: (
                not (
                    any(w in o.lower() for w in ["lol", "omg", "bruh"])
                    and any(w in o.lower() for w in ["hereby", "pursuant", "whereas"])
                )
            ),
        },
        {
            "name": "brand_keywords",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in c.get("brand_keywords", ["innovative", "trusted", "leading"])
            ),
        },
        {
            "name": "personality_match",
            "weight": 25,
            "check": lambda o, c: len(o.split("!")) < 5 and len(o.split("?")) < 10,
        },
        {
            "name": "no_competitor_mentions",
            "weight": 25,
            "check": lambda o, c: not any(w in o.lower() for w in c.get("competitors", [])),
        },
    ]


class CTAClarity(RubricEval):
    department = "marketing"
    eval_name = "cta_clarity"
    criteria: ClassVar = [
        {
            "name": "has_cta",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower()
                for w in [
                    "sign up",
                    "get started",
                    "learn more",
                    "try",
                    "buy",
                    "subscribe",
                    "download",
                    "contact",
                ]
            ),
        },
        {
            "name": "single_primary_cta",
            "weight": 25,
            "check": lambda o, c: (
                sum(1 for w in ["sign up", "get started", "buy now", "subscribe"] if w in o.lower())
                <= 2
            ),
        },
        {
            "name": "urgency",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["today", "now", "limited", "don't miss", "exclusive", "free"]
            ),
        },
        {
            "name": "benefit_clear",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["save", "get", "unlock", "discover", "transform", "boost"]
            ),
        },
    ]


class AudienceTargeting(RubricEval):
    department = "marketing"
    eval_name = "audience_targeting"
    criteria: ClassVar = [
        {
            "name": "identifies_audience",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["you", "your", "customer", "user", "professional", "team"]
            ),
        },
        {
            "name": "addresses_pain_point",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["struggle", "challenge", "problem", "tired of", "frustrated", "pain"]
            ),
        },
        {
            "name": "speaks_their_language",
            "weight": 25,
            "check": lambda o, c: (
                len(o.split()) > 20 and not any(w in o.lower() for w in ["synergy", "paradigm"])
            ),
        },
        {
            "name": "relevant_examples",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["example", "like", "such as", "imagine", "picture this"]
            ),
        },
    ]


class ChannelFit(RubricEval):
    department = "marketing"
    eval_name = "channel_fit"
    criteria: ClassVar = [
        {
            "name": "appropriate_length",
            "weight": 25,
            "check": lambda o, c: len(o.split()) <= c.get("max_words", 500),
        },
        {
            "name": "format_correct",
            "weight": 25,
            "check": lambda o, c: (
                bool(re.search(r"#{1,3}\s|^\-\s|\*\*", o, re.MULTILINE)) or len(o) < 280
            ),
        },
        {
            "name": "visual_cues",
            "weight": 25,
            "check": lambda o, c: (
                any(w in o for w in ["📧", "🎯", "✅", "→", "•", "—"]) or "image" in o.lower()
            ),
        },
        {
            "name": "platform_conventions",
            "weight": 25,
            "check": lambda o, c: "#" in o or "@" in o or "http" in o or len(o.split("\n\n")) >= 2,
        },
    ]


class Measurability(RubricEval):
    department = "marketing"
    eval_name = "measurability"
    criteria: ClassVar = [
        {
            "name": "has_metrics",
            "weight": 30,
            "check": lambda o, c: any(
                w in o.lower()
                for w in ["conversion", "ctr", "open rate", "engagement", "roi", "cac", "ltv"]
            ),
        },
        {
            "name": "has_targets",
            "weight": 25,
            "check": lambda o, c: bool(
                re.search(r"\d+%|\d+x|\d+\s*(leads|clicks|views|users)", o.lower())
            ),
        },
        {
            "name": "tracking_plan",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["track", "measure", "analytics", "utm", "pixel", "tag"]
            ),
        },
        {
            "name": "timeline",
            "weight": 20,
            "check": lambda o, c: any(
                w in o.lower() for w in ["week", "month", "quarter", "daily", "weekly", "by"]
            ),
        },
    ]


ALL_EVALS = [BrandVoice, CTAClarity, AudienceTargeting, ChannelFit, Measurability]
