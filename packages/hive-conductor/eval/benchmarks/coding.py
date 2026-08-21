"""Coding eval — SWE-bench style pass/fail on code generation tasks.

Presents coding problems with test cases. Scores based on:
  - Tests pass (70 pts)
  - Code is syntactically valid (15 pts)
  - No obvious security issues (15 pts)
"""

from __future__ import annotations

import ast
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

TASKS = [
    {
        "id": "c1",
        "prompt": "Write a Python function `fibonacci(n)` that returns the nth Fibonacci number (0-indexed, fib(0)=0, fib(1)=1).",
        "tests": ["fibonacci(0)==0", "fibonacci(1)==1", "fibonacci(10)==55"],
    },
    {
        "id": "c2",
        "prompt": "Write a Python function `is_palindrome(s)` that returns True if the string is a palindrome (case-insensitive, ignoring spaces).",
        "tests": [
            "is_palindrome('racecar')==True",
            "is_palindrome('hello')==False",
            "is_palindrome('A man a plan a canal Panama'.replace(' ',''))==True",
        ],
    },
    {
        "id": "c3",
        "prompt": "Write a Python function `flatten(lst)` that flattens a nested list.",
        "tests": [
            "flatten([1,[2,[3]]])==[1,2,3]",
            "flatten([])==[]",
            "flatten([[1,2],[3]])==[1,2,3]",
        ],
    },
    {
        "id": "c4",
        "prompt": "Write a Python function `most_common(lst)` that returns the most common element.",
        "tests": ["most_common([1,2,2,3])==2", "most_common(['a','b','a'])==('a')"],
    },
    {
        "id": "c5",
        "prompt": "Write a Python function `merge_sorted(a, b)` that merges two sorted lists into one sorted list.",
        "tests": ["merge_sorted([1,3],[2,4])==[1,2,3,4]", "merge_sorted([],[1])==[1]"],
    },
]

_SECURITY_PATTERNS = [re.compile(r"(os\.system|subprocess|eval\(|exec\(|__import__)")]


@dataclass(frozen=True)
class EvalResult:
    score: int
    details: dict[str, Any]


def _extract_code(response: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", response, re.DOTALL)
    return m.group(1).strip() if m else response.strip()


async def run(llm_call: Callable[[str, str], Awaitable[str]], n_tasks: int = 5) -> EvalResult:
    tasks = TASKS[:n_tasks]
    total = 0
    details: dict[str, Any] = {"tasks": []}

    for t in tasks:
        response = await llm_call("Write only Python code. No explanation needed.", t["prompt"])
        code = _extract_code(response)

        # Syntax check
        try:
            ast.parse(code)
            valid_syntax = True
        except SyntaxError:
            valid_syntax = False

        # Security check
        has_security_issue = any(p.search(code) for p in _SECURITY_PATTERNS)

        # Test execution
        tests_passed = 0
        if valid_syntax:
            try:
                ns: dict[str, Any] = {}
                exec(code, ns)
                for test_expr in t["tests"]:
                    try:
                        if eval(test_expr, ns):
                            tests_passed += 1
                    except Exception:
                        pass
            except Exception:
                pass

        test_score = int(70 * tests_passed / len(t["tests"])) if t["tests"] else 0
        score = test_score + (15 if valid_syntax else 0) + (15 if not has_security_issue else 0)
        total += score
        details["tasks"].append(
            {
                "id": t["id"],
                "tests_passed": tests_passed,
                "total_tests": len(t["tests"]),
                "score": score,
            }
        )

    return EvalResult(score=total // len(tasks), details=details)
