"""Detect docstrings that were made *less specific* — a documentation regression.

``code_quality`` scores docstring **coverage** (via ``interrogate``): it rewards a
symbol *having* a docstring but is blind to a docstring's *content*. So rewriting
a precise docstring into a vaguer paraphrase keeps coverage at 100% and costs
nothing — exactly how an RSI cycle once replaced a docstring that named GEPA,
MIPROv2, DSPy, and SPEC-202 with a generic summary and still passed every gate.

This module compares the docstrings of symbols present in *both* the baseline and
the candidate and flags a **material specificity loss**: the docstring both shrank
and dropped concrete technical references (backtick refs, ADR/SPEC ids, URLs,
identifiers with digits/intra-word capitals, ALLCAPS acronyms). It is deliberately
conservative — pure rewording that keeps the references, and trivial trims, are not
flagged — so it can back a hard veto (``no_doc_regression``) without punishing
legitimate edits. Adding a brand-new docstring is never a regression.
"""

from __future__ import annotations

import ast
import re

# A docstring must shrink to below this fraction of the original length AND lose
# at least this many specific tokens to count as a regression. Two conditions so
# a faithful reword (keeps tokens) or a small trim (barely shrinks) is tolerated.
_SHRINK_RATIO = 0.75
_MIN_LOST_TOKENS = 2

_BACKTICK = re.compile(r"`([^`]+)`")
_ADR_SPEC = re.compile(r"\b(?:ADR|SPEC)-[A-Za-z0-9-]+", re.IGNORECASE)
_URL = re.compile(r"https?://\S+")
_HAS_DIGIT = re.compile(r"\b\w*\d\w*\b")
_ALLCAPS = re.compile(r"\b[A-Z]{2,}\b")
_INTRA_CAPS = re.compile(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z0-9]*\b")


def _specific_tokens(text: str) -> set[str]:
    """The concrete technical references in ``text`` — the things a vague rewrite
    tends to drop: `backtick` refs, ADR/SPEC ids, URLs, identifiers with digits or
    intra-word capitals (``MIPROv2``, ``DSPy``), and ALLCAPS acronyms (``GEPA``)."""
    tokens: set[str] = set()
    tokens |= set(_BACKTICK.findall(text))
    tokens |= set(_ADR_SPEC.findall(text))
    tokens |= set(_URL.findall(text))
    tokens |= set(_HAS_DIGIT.findall(text))
    tokens |= set(_ALLCAPS.findall(text))
    tokens |= set(_INTRA_CAPS.findall(text))
    return {t.strip() for t in tokens if t.strip()}


def _docstrings(source: str) -> dict[str, str]:
    """Map ``qualname -> docstring`` for the module, classes, and functions in
    ``source``. Undocumented symbols and parse errors are simply omitted."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, str] = {}
    module_doc = ast.get_docstring(tree)
    if module_doc:
        out["<module>"] = module_doc

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}{child.name}"
                doc = ast.get_docstring(child)
                if doc:
                    out[qual] = doc
                visit(child, f"{qual}.")

    visit(tree, "")
    return out


def doc_regressions(baseline_src: str, candidate_src: str) -> list[str]:
    """Return a description of each symbol whose docstring lost material specificity.

    Empty list ⇒ no regression (the common, allowed case, including newly added
    docstrings and faithful rewordings). Each entry names the symbol and what it
    lost, for an auditable gate reason.
    """
    base = _docstrings(baseline_src)
    cand = _docstrings(candidate_src)
    regressions: list[str] = []
    for qual, base_doc in base.items():
        cand_doc = cand.get(qual)
        if not cand_doc:  # removed entirely, or symbol gone — not this check's job
            continue
        shrank = len(cand_doc) < _SHRINK_RATIO * len(base_doc)
        lost = _specific_tokens(base_doc) - _specific_tokens(cand_doc)
        if shrank and len(lost) >= _MIN_LOST_TOKENS:
            sample = ", ".join(sorted(lost)[:4])
            regressions.append(
                f"{qual}: docstring shrank {len(base_doc)}→{len(cand_doc)} chars and dropped "
                f"specifics ({sample})"
            )
    return regressions
