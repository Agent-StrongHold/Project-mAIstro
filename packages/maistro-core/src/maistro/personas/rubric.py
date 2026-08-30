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

from maistro.personas.schema import EvalSpec, PersonaTemplate, PersonaTemplateSource
from maistro.personas.vocabulary import evaluate

DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "templates"
PERSONA_TEMPLATE_YAML = "persona_template_yaml"
LEGACY_DEPARTMENT_YAML = "legacy_department_yaml"


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


def _source_format(data: dict[str, Any]) -> str:
    """Classify the raw shape before PersonaTemplate normalizes it.

    The legacy marker is deliberately the same structural condition the schema
    uses for its compatibility normalization. Looking at the normalized model
    afterwards would erase the fact we need to preserve for migration.
    """

    if "id" not in data and "department" in data:
        return LEGACY_DEPARTMENT_YAML
    return PERSONA_TEMPLATE_YAML


def load_template(path: str | Path) -> PersonaTemplate:
    """Load one template YAML and attach loader-attested source provenance."""
    source_path = Path(path)
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Template {path} is not a YAML mapping")
    provenance = PersonaTemplateSource(
        source_format=_source_format(data),
        source_locator=str(source_path),
    )
    # Treat these as an attestation contract, not merely fields we happen to
    # populate. An empty observed format or locator means the loader cannot
    # prove where the normalized reusable definition came from.
    if not provenance.source_format or not provenance.source_locator:
        raise RuntimeError("Persona template source attestation is incomplete")

    # Provenance is evidence produced by the loader, not template content. A
    # source may contain this key because it was hand-edited or came from an
    # older exporter, but it cannot self-assert what format/location produced
    # the normalized object and cannot break parsing with a malformed value.
    template_data = dict(data)
    template_data.pop("source_provenance", None)
    template = PersonaTemplate(**template_data).model_copy(update={"source_provenance": provenance})
    # Read the attached field back rather than assuming model_copy accepted it:
    # downstream migration code relies on this evidence being present.
    if template.source_provenance != provenance:
        raise RuntimeError("Persona template source attestation was not retained")
    return template


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
