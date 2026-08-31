#!/usr/bin/env python3
"""Gate the unauthenticated route surface against a trusted base (#316, #542).

Every public path must still be declared, owned, justified, correctly shaped and
unexpired in the candidate registry. In addition, a route identity ``(path,
matching kind)`` that is public now but was not in the registry at the merge
base is a security-surface expansion and requires a separately landed
authorization. A candidate therefore cannot make a new bypass, or widen an
existing bypass from boundary-safe matching to loose-prefix matching, acceptable
by editing the route and registry in one commit.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MIDDLEWARE = ROOT / "packages" / "hive-conductor" / "backend" / "middleware" / "auth.py"
REGISTRY = ROOT / "quality" / "public-routes.json"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "public-routes"
METRIC_DEFINITION_VERSION = "2"
_GIT_TIMEOUT_SECONDS = 60

DECLARATIONS: dict[str, str] = {
    "_PUBLIC_PREFIXES": "prefix",
    "_PUBLIC_PREFIXES_LOOSE": "loose-prefix",
    "_PUBLIC_EXACT": "exact",
}
REQUIRED = ("kind", "owner", "risk", "disposition", "reason")
REQUIRED_TEMPORARY = ("issue", "expires")
RISKS = frozenset({"low", "medium", "high"})
DISPOSITIONS = frozenset({"permanent", "temporary"})


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
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


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"git {' '.join(args)} could not run: {exc}") from exc


def _unshallow_ci_checkout(prov: ModuleType, event_base: str) -> None:
    shallow = _run_git(["rev-parse", "--is-shallow-repository"])
    if shallow.returncode != 0:
        raise prov.RatchetProvenanceError(
            f"could not determine checkout depth before resolving {event_base!r}: "
            f"{shallow.stderr.strip()}"
        )
    if shallow.stdout.strip() != "true":
        return

    current_ref = os.environ.get("GITHUB_REF", "").strip()
    if not current_ref:
        raise prov.RatchetProvenanceError(
            f"GitHub Actions checkout is shallow while resolving {event_base!r}, "
            "but GITHUB_REF is unavailable to materialize the candidate ancestry"
        )
    fetched = _run_git(["fetch", "--no-tags", "--unshallow", "origin", current_ref])
    if fetched.returncode != 0:
        raise prov.RatchetProvenanceError(
            f"could not unshallow GitHub event ref {current_ref!r}: {fetched.stderr.strip()}"
        )


def _materialize_event_base(prov: ModuleType, event_base: str) -> None:
    if event_base.startswith("origin/"):
        branch = event_base.removeprefix("origin/")
        fetched = _run_git(
            [
                "fetch",
                "--no-tags",
                "origin",
                f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
            ]
        )
        if fetched.returncode != 0:
            raise prov.RatchetProvenanceError(
                f"could not materialize trusted base {event_base!r}: {fetched.stderr.strip()}"
            )
        return

    probe = _run_git(["rev-parse", "--verify", f"{event_base}^{{commit}}"])
    if probe.returncode == 0:
        return
    fetched = _run_git(["fetch", "--no-tags", "origin", event_base])
    if fetched.returncode != 0:
        raise prov.RatchetProvenanceError(
            f"could not materialize trusted base {event_base!r}: {fetched.stderr.strip()}"
        )


def _materialize_ci_history(prov: ModuleType) -> None:
    """Make the event-selected trusted base readable from a shallow Actions checkout.

    ``actions/checkout`` defaults to depth one. On pull requests that leaves the
    synthetic merge itself marked shallow and omits ``origin/<base>`` entirely,
    so even a correct trusted-base resolver cannot calculate the merge base.
    Materialize only the current event ref and its declared integration target;
    never substitute the candidate ledger when that fetch fails.
    """
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return

    event_base = prov._github_event_base()
    if not event_base:
        return
    _unshallow_ci_checkout(prov, event_base)
    _materialize_event_base(prov, event_base)


def declared_paths(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        for name in names & DECLARATIONS.keys():
            for literal in ast.walk(node.value):
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    found[literal.value] = DECLARATIONS[name]
    return found


def _shape_problems(path: str, entry: dict[str, Any], kind: str) -> list[str]:
    problems = []
    if entry["kind"] != kind:
        problems.append(
            f"  {path}: declared as {entry['kind']!r} but auth.py makes it {kind!r} — "
            f"the two match differently, so the registry would describe the wrong exemption"
        )
    if entry["risk"] not in RISKS:
        problems.append(f"  {path}: risk {entry['risk']!r} is not one of {sorted(RISKS)}")
    if entry["disposition"] not in DISPOSITIONS:
        problems.append(
            f"  {path}: disposition {entry['disposition']!r} is not one of {sorted(DISPOSITIONS)}"
        )
    return problems


def _expiry_problems(path: str, entry: dict[str, Any], today: date) -> list[str]:
    missing = [
        f"  {path}: a temporary exemption must name {field!r}"
        for field in REQUIRED_TEMPORARY
        if not entry.get(field)
    ]
    if missing:
        return missing
    try:
        expires = date.fromisoformat(str(entry["expires"]))
    except ValueError:
        return [f"  {path}: expires {entry['expires']!r} is not a YYYY-MM-DD date"]
    if expires < today:
        return [
            f"  {path}: the exemption expired on {expires.isoformat()} — close it "
            f"(#{entry['issue']}) or re-justify it with a new date and a reason "
            f"that survives review a second time"
        ]
    return []


def _entry_problems(path: str, entry: Any, kind: str, today: date) -> list[str]:
    if not isinstance(entry, dict):
        return [f"  {path}: registry entry is not an object"]
    missing = [f"  {path}: missing {field!r}" for field in REQUIRED if not entry.get(field)]
    if missing:
        return missing
    problems = _shape_problems(path, entry, kind)
    if problems or entry["disposition"] != "temporary":
        return problems
    return _expiry_problems(path, entry, today)


def _registry(loaded: object) -> dict[str, Any]:
    if not isinstance(loaded, dict):
        return {}
    routes = loaded.get("routes")
    return dict(routes) if isinstance(routes, dict) else {}


def _registry_identities(registry: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (path, str(entry.get("kind")))
        for path, entry in registry.items()
        if isinstance(entry, dict) and entry.get("kind")
    }


def audit_registry(
    declared: dict[str, str], registry: dict[str, Any], today: date | None = None
) -> list[str]:
    """One message per disagreement between middleware and one registry snapshot."""
    today = today or date.today()
    failures: list[str] = []
    for path, kind in sorted(declared.items()):
        entry = registry.get(path)
        if entry is None:
            failures.append(
                f"  {path}: public in {MIDDLEWARE.name} and absent from "
                f"{REGISTRY.name} — a bypass nobody signed"
            )
            continue
        failures.extend(_entry_problems(path, entry, kind, today))
    for path in sorted(set(registry) - set(declared)):
        failures.append(
            f"  {path}: declared in {REGISTRY.name} and not public in "
            f"{MIDDLEWARE.name} — a stale entry pre-approves whoever adds it back"
        )
    return failures


def audit(today: date | None = None) -> list[str]:
    """Candidate-registry audit retained as the public/test-facing helper."""
    declared = declared_paths(MIDDLEWARE.read_text(encoding="utf-8"))
    registry = _registry(json.loads(REGISTRY.read_text(encoding="utf-8")))
    return audit_registry(declared, registry, today)


def main() -> int:
    for required in (MIDDLEWARE, REGISTRY):
        if not required.is_file():
            print(f"FAIL: {required} does not exist", file=sys.stderr)
            return 1

    declared = declared_paths(MIDDLEWARE.read_text(encoding="utf-8"))
    candidate = _registry(json.loads(REGISTRY.read_text(encoding="utf-8")))
    candidate_failures = audit_registry(declared, candidate)

    prov = _provenance()
    try:
        _materialize_ci_history(prov)
        trusted_ref = prov.resolve_baseline(REGISTRY, root=ROOT)
        trusted = _registry(trusted_ref.loads(default={"routes": {}}))
        prov.require_measurement(declared, ratchet=RATCHET, what="public routes")
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except (RuntimeError, prov.RatchetProvenanceError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    current_identities = set(declared.items())
    trusted_identities = _registry_identities(trusted)
    added_identities = sorted(current_identities - trusted_identities)
    affected_paths = sorted({path for path, _kind in added_identities})
    unauthorized = [path for path in affected_paths if path not in authorized]
    unbanked_authorized = [
        path for path in affected_paths if path in authorized and path not in candidate
    ]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted_identities)} public route identities",
            new_value=f"{len(current_identities)} public route identities",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{path}: {authorized[path]}" for path in affected_paths if path in authorized
            ),
        ).render()
    )

    failures = list(candidate_failures)
    for path in unauthorized:
        trusted_entry = trusted.get(path)
        old_kind = trusted_entry.get("kind") if isinstance(trusted_entry, dict) else None
        if old_kind is None:
            failures.append(
                f"  {path}: NEW unauthenticated path is absent from the trusted base and has no "
                "already-landed authorization"
            )
        else:
            failures.append(
                f"  {path}: unauthenticated matching kind changed from {old_kind!r} to "
                f"{declared[path]!r} without already-landed authorization"
            )
    failures.extend(
        f"  {path}: authorized public-surface expansion is not recorded in the candidate registry"
        for path in unbanked_authorized
    )

    if failures:
        print(f"FAIL: {len(failures)} problem(s) with the unauthenticated route surface:\n")
        print("\n".join(failures))
        print(
            "\nA new public route or matching-kind expansion requires its registry entry plus a "
            "separately landed authorization. Existing entries remain ordinary reviewed policy "
            "and must stay owned, justified, correctly shaped, and unexpired."
        )
        return 1

    print(f"ok: all {len(declared)} unauthenticated path(s) are declared and base-authorized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
