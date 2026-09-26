#!/usr/bin/env python3
"""Run quality-workflow ratchets against a trusted-base floor.

The quality workflow used to carry these floors as YAML literals. That made a
metric and its oracle editable in one candidate change. This checker keeps the
measurement in the candidate tree, but resolves every comparison floor from
``quality/workflow-ratchet-baseline.json`` at the trusted merge base.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "workflow-ratchet-baseline.json"
_PROVENANCE_SOURCE = Path(__file__).resolve().parent / "ratchet_provenance.py"
RATCHET = "workflow-quality"
METRIC_DEFINITION_VERSION = "1"

# The keys are intentionally code-owned: the candidate may change measured
# values, but cannot add a new metric without changing this checker and its
# inventory contract.
EXPECTED: dict[str, tuple[str, str, str]] = {
    "coverage": ("minimum", "coverage report --format=total", "percent"),
    "xenon": ("maximum", "xenon --max-absolute B --max-modules B --max-average A", "count"),
    "pyright": ("maximum", "pyright --outputjson packages/maistro-core/src", "errors"),
    "interrogate:graph/nodes": ("minimum", "interrogate -f 0 -v graph/nodes", "percent"),
    "interrogate:graph/durable_runs": (
        "minimum",
        "interrogate -f 0 -v graph/durable_runs",
        "percent",
    ),
    "interrogate:projects": ("minimum", "interrogate -f 0 -v projects", "percent"),
    "interrogate:all": ("minimum", "interrogate -f 0 -v maistro", "percent"),
}
INTERROGATE_PATHS = {
    "interrogate:graph/nodes": "packages/maistro-core/src/maistro/graph/nodes",
    "interrogate:graph/durable_runs": "packages/maistro-core/src/maistro/graph/durable_runs",
    "interrogate:projects": "packages/maistro-core/src/maistro/projects",
    "interrogate:all": "packages/maistro-core/src/maistro",
}
_PERCENT_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)%")
_XENON_BLOCK_RE = re.compile(r"^ERROR:xenon:block", re.MULTILINE)
_LEGACY_PATTERNS = {
    "coverage": re.compile(r"coverage report --fail-under[= ](\d+(?:\.\d+)?)"),
    "xenon": re.compile(r"XENON_BASELINE:\s*(\d+(?:\.\d+)?)"),
    "pyright": re.compile(r"PYRIGHT_BASELINE:\s*(\d+(?:\.\d+)?)"),
    "interrogate:graph/nodes": re.compile(
        r"interrogate -f (\d+(?:\.\d+)?) packages/maistro-core/src/maistro/graph/nodes"
    ),
    "interrogate:graph/durable_runs": re.compile(
        r"interrogate -f (\d+(?:\.\d+)?) packages/maistro-core/src/maistro/graph/durable_runs"
    ),
    "interrogate:projects": re.compile(
        r"interrogate -f (\d+(?:\.\d+)?) packages/maistro-core/src/maistro/projects"
    ),
    "interrogate:all": re.compile(
        r"interrogate -f (\d+(?:\.\d+)?) packages/maistro-core/src/maistro(?:\s|$)"
    ),
}


class WorkflowRatchetError(RuntimeError):
    """The trusted floor or a tool measurement cannot establish a verdict."""


@dataclass(frozen=True)
class TrustedFloor:
    reference: Any
    value: float
    direction: str
    tool: str
    unit: str


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_workflow_ratchet_provenance", _PROVENANCE_SOURCE
    )
    if spec is None or spec.loader is None:
        raise WorkflowRatchetError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def _legacy_floors(prov: ModuleType, root: Path) -> dict[str, TrustedFloor]:
    legacy_workflow = prov.resolve_baseline(
        root / ".github" / "workflows" / "quality.yml", root=root
    )
    legacy_script = prov.resolve_baseline(root / "scripts" / "check-diff-coverage.py", root=root)
    if legacy_workflow.text is None or legacy_script.text is None:
        raise WorkflowRatchetError(
            "workflow quality baseline is absent at the trusted base and its legacy floor "
            "is unavailable"
        )
    source = legacy_workflow.text + "\n" + legacy_script.text
    floors: dict[str, TrustedFloor] = {}
    for name, (direction, tool, unit) in EXPECTED.items():
        match = _LEGACY_PATTERNS[name].search(source)
        if match is None:
            raise WorkflowRatchetError(
                f"workflow quality baseline is absent and legacy metric {name!r} is missing"
            )
        floors[name] = TrustedFloor(legacy_workflow, float(match.group(1)), direction, tool, unit)
    return floors


def _recorded_floors(prov: ModuleType, reference: Any) -> dict[str, TrustedFloor]:
    payload = reference.loads()
    if not isinstance(payload, dict):
        raise WorkflowRatchetError("workflow quality baseline must be a JSON object")
    prov.require_metric_version(
        METRIC_DEFINITION_VERSION,
        recorded=str(payload.get("metric_definition_version"))
        if payload.get("metric_definition_version") is not None
        else None,
        ratchet=RATCHET,
        baseline=reference,
    )
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise WorkflowRatchetError("workflow quality baseline has no metrics object")
    floors: dict[str, TrustedFloor] = {}
    for name, (direction, tool, unit) in EXPECTED.items():
        record = metrics.get(name)
        if not isinstance(record, dict):
            raise WorkflowRatchetError(f"trusted workflow baseline is missing metric {name!r}")
        if record.get("direction") != direction or record.get("unit") != unit:
            raise WorkflowRatchetError(f"trusted workflow metric {name!r} has changed definition")
        if record.get("tool") != tool:
            raise WorkflowRatchetError(f"trusted workflow metric {name!r} has changed tool")
        value = record.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WorkflowRatchetError(f"trusted workflow metric {name!r} has no numeric floor")
        floors[name] = TrustedFloor(reference, float(value), direction, tool, unit)
    return floors


def _validate_candidate(floors: dict[str, TrustedFloor], root: Path) -> None:
    path = root / BASELINE.relative_to(ROOT)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowRatchetError(
            f"candidate workflow quality baseline is unreadable: {exc}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("metric_definition_version") != METRIC_DEFINITION_VERSION
    ):
        raise WorkflowRatchetError("candidate workflow quality baseline has a changed definition")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise WorkflowRatchetError("candidate workflow quality baseline has no metrics object")
    for name, floor in floors.items():
        record = metrics.get(name)
        if not isinstance(record, dict) or record.get("direction") != floor.direction:
            raise WorkflowRatchetError(f"candidate workflow metric {name!r} has changed definition")
        value = record.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WorkflowRatchetError(f"candidate workflow metric {name!r} has no numeric floor")
        weakened = value < floor.value if floor.direction == "minimum" else value > floor.value
        if weakened:
            raise WorkflowRatchetError(
                f"candidate workflow metric {name!r} weakens the trusted floor; "
                "floor reductions require a separate governance change"
            )


def _trusted_floors(root: Path = ROOT) -> dict[str, TrustedFloor]:
    prov = _provenance()
    reference = prov.resolve_baseline(root / BASELINE.relative_to(ROOT), root=root)
    if reference.absent_at_base:
        # The first migration inherits old inline floors from the trusted tree.
        floors = _legacy_floors(prov, root)
    else:
        floors = _recorded_floors(prov, reference)
    _validate_candidate(floors, root)
    return floors


def _tool_command(name: str) -> list[str]:
    executable = shutil.which(name)
    return [executable] if executable else [sys.executable, "-m", name]


def _run(command: list[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkflowRatchetError(f"{command[0]} could not run: {exc}") from exc


def _percent(output: str, *, metric: str) -> float:
    values = [float(match) for match in _PERCENT_RE.findall(output)]
    if not values:
        raise WorkflowRatchetError(f"{metric}: tool returned no percentage measurement")
    return values[-1]


def _measure(name: str, *, root: Path = ROOT) -> float:
    if name == "coverage":
        proc = _run([*_tool_command("coverage"), "report", "--format=total"], root=root)
        if proc.returncode != 0:
            raise WorkflowRatchetError(
                f"coverage failed: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return _percent(proc.stdout, metric=name)

    if name == "xenon":
        proc = _run(
            [
                *_tool_command("xenon"),
                "--max-absolute",
                "B",
                "--max-modules",
                "B",
                "--max-average",
                "A",
                "packages/maistro-core/src",
            ],
            root=root,
        )
        output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
        count = float(len(_XENON_BLOCK_RE.findall(output)))
        if proc.returncode != 0 and count == 0:
            raise WorkflowRatchetError(f"xenon failed without a measurement: {output.strip()}")
        return count

    if name == "pyright":
        proc = _run(
            [*_tool_command("pyright"), "--outputjson", "packages/maistro-core/src"], root=root
        )
        try:
            payload = json.loads(proc.stdout)
            summary = payload["summary"]
            errors = summary["errorCount"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkflowRatchetError(
                f"pyright returned no readable JSON measurement: {proc.stdout[:200]!r}"
            ) from exc
        if isinstance(errors, bool) or not isinstance(errors, int):
            raise WorkflowRatchetError("pyright errorCount is not an integer")
        return float(errors)

    path = root / INTERROGATE_PATHS[name]
    proc = _run([*_tool_command("interrogate"), "-f", "0", "-v", str(path)], root=root)
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    if proc.returncode != 0:
        raise WorkflowRatchetError(f"{name} failed: {output.strip()}")
    return _percent(output, metric=name)


def _passes(measured: float, floor: TrustedFloor) -> bool:
    return measured >= floor.value if floor.direction == "minimum" else measured <= floor.value


def check(name: str, *, root: Path = ROOT) -> int:
    floors = _trusted_floors(root)
    floor = floors[name]
    measured = _measure(name, root=root)
    prov = _provenance()
    print(
        prov.Provenance(
            ratchet=f"{RATCHET}:{name}",
            baseline=floor.reference,
            tool=floor.tool,
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{floor.value:g} {floor.unit}",
            new_value=f"{measured:g} {floor.unit}",
            candidate_sha=prov.head_sha(root),
        ).render()
    )
    if _passes(measured, floor):
        print(f"OK: {name} {measured:g} meets trusted {floor.direction} floor {floor.value:g}")
        return 0
    print(
        f"FAIL: {name} {measured:g} violates trusted {floor.direction} floor {floor.value:g}",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metric", choices=tuple(EXPECTED))
    args = parser.parse_args(argv)
    try:
        return check(args.metric)
    except (WorkflowRatchetError, ValueError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
