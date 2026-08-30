#!/usr/bin/env python3
"""Fail M1 changes that create a new architecture island without review.

Issue #460 is the policy layer over the architecture-fitness vocabulary created
by #36. The existing execution-lifecycle and model-egress detectors remain the
authoritative detectors for those categories; this checker adds the missing PR
diff guard for new shared-owner-shaped types and convergence-matrix subsystems.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = "docs/architecture/CONVERGENCE-MATRIX.md"
POLICY_PATH = ROOT / "quality" / "m1-convergence-freeze.json"
ONTOLOGY_PATH = ROOT / "quality" / "shared-interop-ontology-v1.json"
OWNERSHIP_MARKER = "<!-- matrix:ownership -->"
PRODUCT_LOCAL_MARKER = "M1 product-local projection:"
SCRIPTS_DIR = ROOT / "scripts"

_AUTHORITY_SUFFIXES = frozenset(
    {
        "Authority",
        "Bus",
        "Lifecycle",
        "Manager",
        "Registry",
        "Repository",
        "Sequence",
        "Service",
        "State",
        "Store",
    }
)


def _load_script(name: str, path: Path) -> ModuleType:
    """Load one existing architecture checker without copying its detector."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    scripts = str(SCRIPTS_DIR)
    inserted = scripts not in sys.path
    if inserted:
        sys.path.insert(0, scripts)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(scripts)
    return module


def _policy() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _ontology() -> dict[str, object]:
    return json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))


def _subsystems(text: str) -> set[str]:
    marker = text.find(OWNERSHIP_MARKER)
    if marker < 0:
        raise ValueError(f"missing {OWNERSHIP_MARKER}")

    rows: list[str] = []
    for raw in text[marker + len(OWNERSHIP_MARKER) :].splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or cells[0] == "Subsystem":
            continue
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue
        rows.append(cells[0])
    if not rows:
        raise ValueError("ownership table contains no subsystem rows")
    return set(rows)


def _git_show(base: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{base}:{path}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"cannot read {path} from {base}: {proc.stderr.strip()}")
    return proc.stdout


def new_subsystems(current: str, base: str) -> set[str]:
    return _subsystems(current) - _subsystems(base)


def _required_plan_fields(policy: dict[str, object]) -> dict[str, str]:
    exception = policy.get("exception_policy")
    if not isinstance(exception, dict):
        raise ValueError("freeze policy has no exception_policy object")
    fields = exception.get("required_plan_fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("freeze policy has no exception_policy.required_plan_fields object")
    return {str(key): str(value) for key, value in fields.items()}


def validate_exception_plan(plan: str, policy: dict[str, object]) -> list[str]:
    """Require a concrete plan; a label alone never authorizes architecture."""
    failures: list[str] = []
    for field, marker in _required_plan_fields(policy).items():
        pattern = re.compile(rf"(?mi)^\s*{re.escape(marker)}\s*(.+?)\s*$")
        match = pattern.search(plan)
        if match is None or not match.group(1).strip():
            failures.append(f"exception plan is missing {field!r} ({marker} <value>)")
    return failures


def check(
    current: str,
    base: str,
    *,
    exception: bool,
    exception_plan: str = "",
    policy: dict[str, object] | None = None,
) -> list[str]:
    policy = policy or _policy()
    added = sorted(new_subsystems(current, base))
    if not added:
        return []
    if not exception:
        return [
            "M1 convergence freeze: new architecture subsystem(s) require the "
            "m1-convergence-exception label: " + ", ".join(added)
        ]
    plan_failures = validate_exception_plan(exception_plan, policy)
    if plan_failures:
        return [
            "M1 convergence freeze: m1-convergence-exception is incomplete: " + failure
            for failure in plan_failures
        ]
    return []


def _camel_words(name: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", name))


def _concept_words(concept: str) -> tuple[str, ...]:
    return _camel_words(concept)


def _contains_concept(name: str, concept: str) -> bool:
    words = _camel_words(name)
    needle = _concept_words(concept)
    if not needle or len(needle) > len(words):
        return False
    width = len(needle)
    return any(
        words[index : index + width] == needle
        for index in range(len(words) - width + 1)
    )


def _class_records(source: str) -> dict[str, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return {
        node.name: ast.get_docstring(node, clean=False) or ""
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }


def _canonical_owner_map(
    policy: dict[str, object], ontology: dict[str, object]
) -> dict[str, tuple[str, ...]]:
    concepts = ontology.get("concepts")
    if not isinstance(concepts, dict):
        raise ValueError("interop ontology has no concepts object")
    owners: dict[str, tuple[str, ...]] = {}
    for concept, record in concepts.items():
        if not isinstance(record, dict) or not str(record.get("owner", "")).strip():
            raise ValueError(f"interop concept {concept!r} has no owner")
        owners[str(concept)] = (str(record["owner"]),)

    supplemental = policy.get("supplemental_shared_owners", {})
    if not isinstance(supplemental, dict):
        raise ValueError("freeze policy supplemental_shared_owners must be an object")
    for concept, prefixes in supplemental.items():
        if not isinstance(prefixes, list) or not prefixes:
            raise ValueError(f"supplemental owner {concept!r} needs owner prefixes")
        owners[str(concept)] = tuple(str(prefix) for prefix in prefixes)
    return owners


def _owner_allows(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def _product_local_concepts(docstring: str) -> set[str]:
    found: set[str] = set()
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped.startswith(PRODUCT_LOCAL_MARKER):
            concept = stripped[len(PRODUCT_LOCAL_MARKER) :].strip()
            if concept:
                found.add(concept)
    return found


def new_shared_owner_violations(
    current_source: str,
    base_source: str,
    *,
    module: str,
    policy: dict[str, object],
    ontology: dict[str, object],
) -> list[str]:
    """Reject newly defined canonical-looking shared types outside their owner."""
    owners = _canonical_owner_map(policy, ontology)
    current = _class_records(current_source)
    existing = set(_class_records(base_source))
    failures: list[str] = []

    for name in sorted(set(current) - existing):
        words = set(_camel_words(name))
        matched = [
            concept
            for concept in owners
            if _contains_concept(name, concept)
            and (
                name == concept
                or bool(words & _AUTHORITY_SUFFIXES)
                or len(_concept_words(concept)) > 1
            )
        ]
        if not matched:
            continue
        local = _product_local_concepts(current[name])
        unauthorized = [
            concept
            for concept in matched
            if not _owner_allows(module, owners[concept]) and concept not in local
        ]
        if not unauthorized:
            continue
        concept_list = ", ".join(sorted(unauthorized))
        failures.append(
            f"{module}::{name}: new shared-owner-shaped type overlaps {concept_list}. "
            "Define canonical shared types in the ontology owner, or document a domain "
            f"projection in the class docstring as '{PRODUCT_LOCAL_MARKER} <Concept>'."
        )
    return failures


def lifecycle_candidates(source: str, module: str) -> dict[str, set[str]]:
    """Use #36's work-state detector verbatim."""
    checker = _load_script(
        "_m1_execution_lifecycles",
        ROOT / "scripts" / "check-execution-lifecycles.py",
    )
    return checker.work_state_enums(source, module)  # type: ignore[no-any-return,attr-defined]


def performs_model_egress(source: str) -> bool:
    """Use #36's model-egress detector verbatim."""
    checker = _load_script(
        "_m1_model_egress",
        ROOT / "scripts" / "check-model-egress.py",
    )
    return bool(checker.performs_egress(source))  # type: ignore[attr-defined]


def validate_authoritative_gate_map(policy: dict[str, object]) -> list[str]:
    """Ensure #460 points at #36's gates instead of creating parallel vocabulary."""
    expected = {
        "execution_lifecycle": "scripts/check-execution-lifecycles.py",
        "model_egress": "scripts/check-model-egress.py",
        "import_boundaries": "packages/maistro-core/tests/fitness/test_import_boundaries.py",
        "shared_ontology": "quality/shared-interop-ontology-v1.json",
    }
    actual = policy.get("authoritative_gates")
    if not isinstance(actual, dict):
        return ["freeze policy has no authoritative_gates object"]
    failures: list[str] = []
    for key, path in expected.items():
        if actual.get(key) != path:
            failures.append(f"authoritative_gates.{key} must be {path!r}")
        if not (ROOT / path).exists():
            failures.append(f"authoritative gate path does not exist: {path}")
    return failures


def _is_production_python(path: str) -> bool:
    if not path.endswith(".py") or "/tests/" in path or Path(path).name.startswith("test_"):
        return False
    return "/src/" in path or path.startswith(
        ("packages/hive-conductor/backend/", "packages/maistro-turing/backend/")
    )


def _module_name(path: str) -> str:
    if "/src/" in path:
        relative = path.split("/src/", 1)[1]
        return relative.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    return path.removesuffix(".py").replace("/", ".")


def _changed_python_pairs(base: str) -> list[tuple[str | None, str]]:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--name-status",
            "--find-renames",
            f"{base}...HEAD",
            "--",
            "packages",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"cannot diff production files from {base}: {proc.stderr.strip()}")

    pairs: list[tuple[str | None, str]] = []
    for raw in proc.stdout.splitlines():
        parts = raw.split("\t")
        if not parts:
            continue
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) == 3:
            old_path, new_path = parts[1], parts[2]
        elif status.startswith(("A", "M")) and len(parts) == 2:
            new_path = parts[1]
            old_path = None if status.startswith("A") else new_path
        else:
            continue
        if _is_production_python(new_path):
            pairs.append((old_path, new_path))
    return pairs


def shared_owner_failures(
    base: str,
    policy: dict[str, object],
    ontology: dict[str, object],
) -> list[str]:
    failures: list[str] = []
    for old_path, new_path in _changed_python_pairs(base):
        current = (ROOT / new_path).read_text(encoding="utf-8", errors="replace")
        base_source = ""
        if old_path is not None:
            proc = subprocess.run(
                ["git", "-C", str(ROOT), "show", f"{base}:{old_path}"],
                text=True,
                capture_output=True,
                check=False,
            )
            if proc.returncode == 0:
                base_source = proc.stdout
        failures.extend(
            new_shared_owner_violations(
                current,
                base_source,
                module=_module_name(new_path),
                policy=policy,
                ontology=ontology,
            )
        )
    return failures


def _exception_plan_from_environment() -> str:
    """Read the reviewed exception plan from explicit env or the PR event body.

    The required Formal Conformance step invokes this script directly and only
    passes ``--exception`` from the PR label. GitHub still exposes the event
    payload to every step as ``GITHUB_EVENT_PATH``; reading the body here keeps
    that existing entry point compatible without duplicating policy in YAML.
    Missing or malformed evidence returns an empty plan, which fails closed when
    an exception is actually needed.
    """
    explicit = os.environ.get("M1_CONVERGENCE_EXCEPTION_PLAN", "")
    if explicit.strip():
        return explicit

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return ""
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return ""
    return str(pull_request.get("body") or "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="git ref for the PR base")
    parser.add_argument("--exception", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = _policy()
    ontology = _ontology()
    failures = validate_authoritative_gate_map(policy)

    current = (ROOT / MATRIX_PATH).read_text(encoding="utf-8")
    base = _git_show(args.base, MATRIX_PATH)
    failures.extend(
        check(
            current,
            base,
            exception=args.exception,
            exception_plan=_exception_plan_from_environment(),
            policy=policy,
        )
    )
    failures.extend(shared_owner_failures(args.base, policy, ontology))

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("M1 convergence freeze: no unapproved new architecture island")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
