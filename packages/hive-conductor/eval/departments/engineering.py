"""Builder/Engineering evals — tests pass, coverage, security, style match, review score."""

from __future__ import annotations

import re
from typing import ClassVar

from eval.departments import RubricEval


class TestsPass(RubricEval):
    department = "engineering"
    eval_name = "tests_pass"
    criteria: ClassVar = [
        {
            "name": "has_test_code",
            "weight": 25,
            "check": lambda o, c: any(w in o for w in ["def test_", "it(", "assert", "expect("]),
        },
        {
            "name": "covers_happy_path",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["success", "valid", "expected", "correct"]
            ),
        },
        {
            "name": "covers_edge_cases",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["edge", "empty", "null", "none", "zero", "boundary"]
            ),
        },
        {
            "name": "covers_error_cases",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["error", "exception", "raise", "throw", "fail"]
            ),
        },
    ]


class Coverage(RubricEval):
    department = "engineering"
    eval_name = "coverage"
    criteria: ClassVar = [
        {
            "name": "tests_all_functions",
            "weight": 30,
            "check": lambda o, c: len(re.findall(r"def test_|it\(|test\(", o)) >= 3,
        },
        {
            "name": "tests_branches",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["if", "else", "branch", "condition"]
            ),
        },
        {
            "name": "integration_test",
            "weight": 25,
            "check": lambda o, c: any(w in o.lower() for w in ["integration", "e2e", "full flow"]),
        },
        {"name": "no_trivial_tests", "weight": 20, "check": lambda o, c: "assert True" not in o},
    ]


class Security(RubricEval):
    department = "engineering"
    eval_name = "security"
    criteria: ClassVar = [
        {
            "name": "input_validation",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["validat", "sanitiz", "escape", "parameteriz"]
            ),
        },
        {
            "name": "no_hardcoded_secrets",
            "weight": 25,
            "check": lambda o, c: (
                not bool(re.search(r"(password|secret|key)\s*=\s*['\"][^'\"]{8,}", o))
            ),
        },
        {
            "name": "auth_checks",
            "weight": 25,
            "check": lambda o, c: any(
                w in o.lower() for w in ["auth", "permission", "token", "jwt"]
            ),
        },
        {
            "name": "error_handling",
            "weight": 25,
            "check": lambda o, c: any(w in o for w in ["try:", "catch", "except", ".catch("]),
        },
    ]


class StyleMatch(RubricEval):
    department = "engineering"
    eval_name = "style_match"
    criteria: ClassVar = [
        {
            "name": "has_docstrings",
            "weight": 30,
            "check": lambda o, c: '"""' in o or "/**" in o or "///" in o,
        },
        {
            "name": "type_annotations",
            "weight": 30,
            "check": lambda o, c: any(
                w in o for w in ["-> ", ": str", ": int", ": list", ": string"]
            ),
        },
        {
            "name": "reasonable_length",
            "weight": 20,
            "check": lambda o, c: all(len(ln) <= 120 for ln in o.split("\n") if ln.strip()),
        },
        {
            "name": "consistent_naming",
            "weight": 20,
            "check": lambda o, c: (
                not (re.search(r"[a-z]_[a-z]", o) and re.search(r"[a-z][A-Z]", o))
            ),
        },
    ]


class ReviewScore(RubricEval):
    department = "engineering"
    eval_name = "review_score"
    criteria: ClassVar = [
        {
            "name": "readable",
            "weight": 25,
            "check": lambda o, c: any(
                ln.strip().startswith("#") or ln.strip().startswith("//") for ln in o.split("\n")
            ),
        },
        {
            "name": "modular",
            "weight": 25,
            "check": lambda o, c: o.count("def ") >= 2 or o.count("function ") >= 2,
        },
        {
            "name": "no_code_smells",
            "weight": 25,
            "check": lambda o, c: not any(w in o for w in ["TODO", "HACK", "FIXME"]),
        },
        {
            "name": "handles_errors",
            "weight": 25,
            "check": lambda o, c: any(w in o for w in ["try:", "catch", "except", "Result<"]),
        },
    ]


ALL_EVALS = [TestsPass, Coverage, Security, StyleMatch, ReviewScore]
