#!/usr/bin/env python3
"""Freeze the set of modules that call a model endpoint directly (#36).

The convergence program's second invariant is "no direct model/tool/effect
provider bypass outside approved Provider implementations". Enforcing it as
written is not yet possible, and the reason is the finding:

`maistro.providers` is a *registry* — catalog, router, protocols, errors — and
contains no HTTP client. It performs no egress. So there is no approved Provider
implementation for anything to be outside of; there are twenty-six modules each
doing their own call. #56 is the work that creates the one egress this invariant
presumes, and it cannot be checked before it exists.

What can be enforced today is the ratchet: this set may not grow. A new module
calling a completions endpoint directly is a new escape from a boundary that is
still being built, and it fails here by name. An entry that stops performing
egress also fails, until it is pruned — so migrating one under #56 forces the
inventory to shrink rather than leaving a stale line behind.

Detection is deliberately the narrow, checkable version: a module both names a
model endpoint path *and* contains an HTTP-call node. `maistro.auth.middleware`
and `maistro.events.bus` name such a path for routing and allowlisting without
calling anything, and are excluded on that basis rather than by hand.

The inventory carries no per-module verdict. Deciding which of the twenty-six are
legitimate providers, which are adapters, and which are escapes is #56's
adjudication, and recording a guess here would give it a false starting point.

Run: `python scripts/check-model-egress.py`
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "quality" / "model-egress.json"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"

#: Path fragments that identify a model endpoint.
_ENDPOINTS = ("chat/completions", "/completions", "/v1/responses")

#: Call attributes that perform or stream an HTTP request.
_HTTP_CALLS = frozenset({"post", "stream", "send", "request"})


def _load_reachability() -> object:
    spec = importlib.util.spec_from_file_location("_reachability", REACHABILITY)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REACHABILITY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_reachability"] = module
    spec.loader.exec_module(module)
    return module


def performs_egress(source: str) -> bool:
    """True when a module both names a model endpoint and calls out over HTTP."""
    if not any(fragment in source for fragment in _ENDPOINTS):
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _HTTP_CALLS
        for node in ast.walk(tree)
    )


def discover() -> set[str]:
    reach = _load_reachability()
    found: set[str] = set()
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        if performs_egress(path.read_text(errors="replace")):
            found.add(reach._display_name(key, reach.FLAT_APPS))  # type: ignore[attr-defined]
    return found


def audit(recorded: set[str], found: set[str]) -> list[str]:
    failures: list[str] = []
    for module in sorted(found - recorded):
        failures.append(
            f"{module}: calls a model endpoint directly and is not in the inventory. "
            "The set of direct callers may not grow while #56 builds the one egress."
        )
    for module in sorted(recorded - found):
        failures.append(
            f"{module}: recorded as calling a model endpoint but no longer does; prune it "
            "so the inventory shrinks with the migration"
        )
    return failures


def main() -> int:
    if not INVENTORY.exists():
        print(f"FAIL: {INVENTORY} is missing", file=sys.stderr)
        return 1
    recorded = set(json.loads(INVENTORY.read_text())["modules"])
    found = discover()
    failures = audit(recorded, found)
    if failures:
        print("FAIL: the direct-model-egress inventory does not match the code\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nRoute the call through the Provider boundary #56 is building, or — if this is "
            "that boundary — add it to the inventory with the reason."
        )
        return 1
    print(f"OK: {len(found)} modules call a model endpoint directly, exactly as inventoried")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
