"""RubricEval + generic YAML loader (ADR-060, SPEC-192 P0).

Loads persona/department templates and returns instantiated :class:`RubricEval`
objects ready to ``await eval.score(output, context)``. A new domain is added
by dropping one YAML file into the templates directory — no Python changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from maistro.personas.schema import EvalSpec, PersonaTemplate
from maistro.personas.vocabulary import evaluate

DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class EvalResult:
    """Result of scoring one output against one eval dimension (0-100)."""

    score: int
    department: str
    eval_name: str
    details: dict[str, Any]


class RubricEval:
    """A rubric-based eval dimension driven by the declarative vocabulary.

    Deterministic, auditable, no network. Criteria checks are vocabulary
    specs (see :mod:`maistro.personas.vocabulary`), never arbitrary Python.
    """

    def __init__(self, department: str, spec: EvalSpec) -> None:
        self.department = department
        self.eval_name = spec.name
        self.tier = spec.tier
        self.criteria: list[dict[str, Any]] = [
            {"name": c.name, "weight": c.weight, "check": dict(c.check)} for c in spec.criteria
        ]

    async def score(self, output: str, context: dict[str, Any] | None = None) -> EvalResult:
        ctx = context or {}
        total_weight = sum(int(c["weight"]) for c in self.criteria)
        earned = 0
        details: dict[str, Any] = {"criteria": []}

        for c in self.criteria:
            passed = evaluate(c["check"], output, ctx)
            points = int(c["weight"]) if passed else 0
            earned += points
            details["criteria"].append(
                {"name": c["name"], "passed": passed, "points": points, "max": c["weight"]}
            )

        score = int(100 * earned / total_weight) if total_weight else 0
        return EvalResult(
            score=score, department=self.department, eval_name=self.eval_name, details=details
        )


def load_template(path: str | Path) -> PersonaTemplate:
    """Load and validate one template YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Template {path} is not a YAML mapping")
    return PersonaTemplate(**data)


def load_evals(path: str | Path) -> list[RubricEval]:
    """Load a template YAML and return one RubricEval per eval block.

    Accepts both ``kind:``-discriminated persona templates and legacy
    department YAML (``department:`` + ``evals:``).
    """
    template = load_template(path)
    return evals_for(template)


def evals_for(template: PersonaTemplate) -> list[RubricEval]:
    """Instantiate the RubricEvals declared by an already-loaded template."""
    return [RubricEval(template.id, spec) for spec in template.evals]


def load_templates(directory: str | Path | None = None) -> dict[str, PersonaTemplate]:
    """Load every template in a unified ``templates/`` root, keyed by template id."""
    root = Path(directory) if directory is not None else DEFAULT_TEMPLATES_DIR
    result: dict[str, PersonaTemplate] = {}
    if not root.exists():
        return result
    for yaml_file in sorted(root.rglob("*.yaml")):
        template = load_template(yaml_file)
        result[template.id] = template
    return result
