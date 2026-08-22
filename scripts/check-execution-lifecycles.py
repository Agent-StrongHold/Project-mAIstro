#!/usr/bin/env python3
"""Fail when a new work-state enum appears unclassified (#36).

The convergence program's central claim is that `Run`/`NodeRun`/`Attempt` is the
*one* execution identity. A second one does not usually arrive as a decision; it
arrives as an enum. Someone needs to track whether a thing is pending, running or
failed, writes the obvious five members, and the repository quietly has another
lifecycle.

So every work-state enum in production code is classified in
`quality/execution-lifecycles.json`, and this gate ratchets against it in both
directions: an enum with no entry fails, and an entry whose enum no longer exists
fails until it is pruned, so the ledger cannot retain slack.

Classification is the point, not detection. `CANONICAL` is the spine itself.
`DOMAIN` is a lifecycle that genuinely is not execution — an event handler's
at-most-once record, a graph's traversal phase — and saying so forces the
distinction to be argued rather than assumed. `CONVERGE` names the issue that
removes it, so the ledger doubles as the work-list.

Deliberately narrow. A class is only a candidate when it subclasses an enum type
*and* at least three of its members are recognisable work states. Broadening the
signature would flood the ledger with false positives, and a gate that cries wolf
teaches people to bank whatever it says — which is worse than no gate, because it
launders a real second lifecycle through a routine `--update`.

Known limitation, stated rather than hidden: this finds enum-shaped lifecycles
only. `services.dag_run_store` folds its states out of events and
`maistro_canvas.canvas.runner` assigns free-text strings, so neither is visible
here. Both are recorded in `docs/architecture/CONVERGENCE-MATRIX.md`.

Run: `python scripts/check-execution-lifecycles.py`
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "execution-lifecycles.json"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"

CLASSIFICATIONS = frozenset({"CANONICAL", "DOMAIN", "CONVERGE"})

#: Enum base classes that make a class a candidate.
_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag"})

#: Member names that read as the state of a unit of work. Three or more of these
#: in one enum is the signature; fewer is some other kind of enumeration.
_WORK_STATES = frozenset(
    {
        "ABORTED",
        "ACTIVE",
        "ASSIGNED",
        "BLOCKED",
        "CANCELED",
        "CANCELLED",
        "CLAIMED",
        "COMPLETE",
        "COMPLETED",
        "DONE",
        "ERROR",
        "FAILED",
        "IN_PROGRESS",
        "PAUSED",
        "PENDING",
        "QUEUED",
        "RETRYING",
        "RUNNING",
        "SKIPPED",
        "SUCCEEDED",
        "TIMED_OUT",
        "TIMEOUT",
        "WAITING",
    }
)

_MIN_WORK_STATES = 3


def _load_reachability() -> object:
    spec = importlib.util.spec_from_file_location("_reachability", REACHABILITY)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REACHABILITY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_reachability"] = module
    spec.loader.exec_module(module)
    return module


def _enum_members(node: ast.ClassDef) -> set[str]:
    return {
        target.id
        for statement in node.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
    }


def _is_enum(node: ast.ClassDef) -> bool:
    bases = {
        base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        for base in node.bases
    }
    return bool(bases & _ENUM_BASES)


def work_state_enums(source: str, module: str) -> dict[str, set[str]]:
    """`module::ClassName` -> the work-state members that qualified it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_enum(node):
            continue
        states = _enum_members(node) & _WORK_STATES
        if len(states) >= _MIN_WORK_STATES:
            found[f"{module}::{node.name}"] = states
    return found


def discover() -> dict[str, set[str]]:
    reach = _load_reachability()
    found: dict[str, set[str]] = {}
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        module = reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        found.update(work_state_enums(path.read_text(errors="replace"), module))
    return found


def audit(ledger: dict[str, object], found: dict[str, set[str]]) -> list[str]:
    """Every way the ledger and the code disagree, named."""
    entries = ledger.get("lifecycles")
    if not isinstance(entries, dict):
        return ["ledger has no 'lifecycles' object"]

    failures: list[str] = []
    for name in sorted(set(found) - set(entries)):
        failures.append(
            f"{name}: an unclassified work-state enum ({', '.join(sorted(found[name]))}). "
            f"Classify it in {LEDGER.name} as one of {', '.join(sorted(CLASSIFICATIONS))}."
        )
    for name in sorted(set(entries) - set(found)):
        failures.append(f"{name}: classified here but no longer found in the code; prune it")

    for name in sorted(set(entries) & set(found)):
        entry = entries[name]
        if not isinstance(entry, dict):
            failures.append(f"{name}: entry must be an object")
            continue
        classification = entry.get("classification")
        if classification not in CLASSIFICATIONS:
            failures.append(
                f"{name}: classification {classification!r} is not one of "
                f"{', '.join(sorted(CLASSIFICATIONS))}"
            )
        if not str(entry.get("rationale", "")).strip():
            failures.append(f"{name}: needs a rationale")
        if classification == "CONVERGE" and not str(entry.get("converged_by", "")).strip():
            failures.append(
                f"{name}: CONVERGE requires 'converged_by' naming the issue that removes it"
            )
    return failures


def main() -> int:
    if not LEDGER.exists():
        print(f"FAIL: {LEDGER} is missing", file=sys.stderr)
        return 1
    ledger = json.loads(LEDGER.read_text())
    found = discover()
    failures = audit(ledger, found)
    if failures:
        print("FAIL: the execution-lifecycle ledger does not match the code\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nA new work-state enum is how a second execution lifecycle gets built without "
            "anyone deciding to. Say which kind it is."
        )
        return 1

    counts: dict[str, int] = {}
    for entry in ledger["lifecycles"].values():
        key = str(entry["classification"])
        counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    print(f"OK: {len(found)} work-state enums, all classified ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
