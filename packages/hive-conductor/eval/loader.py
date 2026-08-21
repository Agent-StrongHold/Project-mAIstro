"""YAML-to-RubricEval loader (ADR-060).

Loads a department or persona YAML template and returns instantiated
RubricEval objects ready to call .score(output, context).

Usage
-----
    evals = load_department("eval/departments/yaml/marketing.yaml")
    result = await evals[0].score(my_text)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from eval.departments import RubricEval
from eval.vocabulary import evaluate


def _make_check(criterion_spec: dict[str, Any]):
    check_spec = dict(criterion_spec["check"])

    def check(output: str, context: dict[str, Any]) -> bool:
        return evaluate(check_spec, output, context)

    return check


def _build_rubric_eval(department: str, eval_spec: dict[str, Any]) -> RubricEval:
    """Build one RubricEval subclass instance from a single eval spec dict."""
    criteria = [
        {
            "name": c["name"],
            "weight": int(c["weight"]),
            "check": _make_check(c),
        }
        for c in eval_spec.get("criteria", [])
    ]
    DynamicEval = type(
        f"Yaml_{department}_{eval_spec['name']}",
        (RubricEval,),
        {
            "department": department,
            "eval_name": eval_spec["name"],
            "criteria": criteria,
        },
    )
    return DynamicEval()


def load_department(path: str | Path) -> list[RubricEval]:
    """Load a department YAML and return one RubricEval per eval block."""
    data = yaml.safe_load(Path(path).read_text())
    department = data["department"]
    return [_build_rubric_eval(department, ev) for ev in data.get("evals", [])]


_YAML_DIR = Path(__file__).parent / "departments" / "yaml"


def all_departments() -> dict[str, list[RubricEval]]:
    """Return {department_name: [RubricEval, ...]} for every YAML template found."""
    result: dict[str, list[RubricEval]] = {}
    if not _YAML_DIR.exists():
        return result
    for yaml_file in sorted(_YAML_DIR.glob("*.yaml")):
        evals = load_department(yaml_file)
        if evals:
            result[evals[0].department] = evals
    return result
