#!/usr/bin/env python3
"""Ratchet authenticated Conductor route prefixes (Workspace cutover P0.2, #53 AC-P2).

Every ``/v1/{segment}`` prefix mounted on the hive app must be declared in
``quality/route-permissions.json`` with exactly one of:

  * ``permission`` -- the ``scope.verb`` the prefix requires, or
  * ``exempt_reason`` -- why it needs none (owner, disposition, and for a
    ``temporary`` exemption an ``issue`` and unexpired ``expires`` date).

Paths declared public in ``quality/public-routes.json`` are out of scope; that
registry has its own gate.

An undeclared prefix is tolerated only while it is in
``quality/route-permissions-baseline.json`` *as of the trusted merge base*
(docs/ci/RATCHET-PROVENANCE.md). Declaring a permission is a tightening and needs
nothing more. Declaring a new exemption widens the reviewed surface, so it needs
an ``exempt::<prefix>`` grant already landed in
``quality/ratchet-authorizations.json`` -- the same rule check-public-routes.py
applies to a new public path. A malformed or stale registry entry always fails.

Run:  uv run python scripts/check-route-permissions.py
Bank: uv run python scripts/check-route-permissions.py --write-baseline
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "quality" / "route-permissions.json"
BASELINE = ROOT / "quality" / "route-permissions-baseline.json"
PUBLIC_REGISTRY = ROOT / "quality" / "public-routes.json"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "route-permissions"
METRIC_DEFINITION_VERSION = "1"

REQUIRED = ("owner", "disposition", "reason")
REQUIRED_TEMPORARY = ("issue", "expires")
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


def _v1_prefix(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) >= 3 and parts[1] == "v1" and parts[2]:
        return f"/v1/{parts[2]}"
    return None


def mounted_prefixes() -> set[str]:
    """Every /v1/{segment} the real hive app mounts (raises if it cannot import)."""
    backend = ROOT / "packages" / "hive-conductor" / "backend"
    for src_root in sorted((ROOT / "packages").glob("*/src")):
        sys.path.insert(0, str(src_root))
    sys.path.insert(0, str(backend))
    os.environ.setdefault("CONDUCTOR_DATA_DIR", "/tmp/route-perm-check-data")
    from main import app  # type: ignore[import-not-found]

    from maistro_server.api.route_table import iter_effective_routes

    prefixes: set[str] = set()
    for route in iter_effective_routes(app.routes):
        path = getattr(route, "path", None)
        prefix = _v1_prefix(path) if isinstance(path, str) else None
        if prefix is not None:
            prefixes.add(prefix)
    return prefixes


def _object(payload: object, key: str) -> dict[str, Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return dict(value) if isinstance(value, dict) else {}


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def entry_problems(prefix: str, entry: Any, today: date) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{prefix}: registry entry is not an object"]
    has_permission = bool(entry.get("permission"))
    has_exempt = bool(entry.get("exempt_reason"))
    if has_permission == has_exempt:
        which = "both" if has_permission else "neither"
        return [f"{prefix}: declare exactly one of 'permission' or 'exempt_reason', not {which}"]
    missing = [f"{prefix}: missing {field!r}" for field in REQUIRED if not entry.get(field)]
    if missing:
        return missing
    if entry["disposition"] not in DISPOSITIONS:
        return [f"{prefix}: disposition must be one of {sorted(DISPOSITIONS)}"]
    if entry["disposition"] != "temporary":
        return []
    missing = [
        f"{prefix}: a temporary entry must name {field!r}"
        for field in REQUIRED_TEMPORARY
        if not entry.get(field)
    ]
    if missing:
        return missing
    try:
        expires = date.fromisoformat(str(entry["expires"]))
    except ValueError:
        return [f"{prefix}: expires {entry['expires']!r} is not YYYY-MM-DD"]
    if expires < today:
        return [f"{prefix}: expired on {expires.isoformat()} -- close it or re-justify it"]
    return []


def registry_problems(
    mounted: set[str], registry: dict[str, Any], public: set[str], today: date
) -> list[str]:
    """Hard failures: malformed entries, and entries for prefixes nobody mounts."""
    problems: list[str] = []
    for prefix, entry in sorted(registry.items()):
        if prefix not in mounted:
            problems.append(f"{prefix}: declared but not mounted -- a stale entry pre-approves it")
        elif prefix in public:
            problems.append(f"{prefix}: public in public-routes.json; it does not belong here")
        else:
            problems.extend(entry_problems(prefix, entry, today))
    return problems


def undeclared(mounted: set[str], registry: dict[str, Any], public: set[str]) -> set[str]:
    return {prefix for prefix in mounted if prefix not in registry and prefix not in public}


def new_exemptions(candidate: dict[str, Any], trusted: dict[str, Any]) -> set[str]:
    """``exempt::<prefix>`` keys for exemptions the trusted registry did not grant."""

    def exempt(registry: dict[str, Any]) -> set[str]:
        return {p for p, e in registry.items() if isinstance(e, dict) and e.get("exempt_reason")}

    return {f"exempt::{prefix}" for prefix in exempt(candidate) - exempt(trusted)}


def compare(
    current: set[str],
    candidate: set[str],
    trusted: set[str],
    exemptions: set[str],
    authorized: set[str],
) -> list[str]:
    added = current - trusted
    failures = [
        f"{key}: NEW undeclared route prefix absent from the trusted base and not "
        "previously authorized"
        for key in sorted(added - authorized)
    ]
    failures.extend(
        f"{key}: authorized new gap is not recorded in the candidate ledger"
        for key in sorted((added & authorized) - candidate)
    )
    failures.extend(
        f"{key}: NEW exemption needs an already-landed authorization"
        for key in sorted(exemptions - authorized)
    )
    failures.extend(
        f"{key}: current gap missing from candidate ledger" for key in sorted(current - candidate)
    )
    failures.extend(
        f"{key}: declared now -- delete it from the candidate ledger"
        for key in sorted(candidate - current)
    )
    return failures


def write_baseline(gaps: set[str]) -> None:
    payload = {
        "_comment": (
            "Undeclared authenticated route prefixes for Workspace cutover P0.2 (#53). "
            "Judged against the trusted merge base; a declared prefix must be deleted here."
        ),
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "tolerated": dict.fromkeys(sorted(gaps), "absent from quality/route-permissions.json"),
    }
    BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current undeclared prefixes in the candidate ledger",
    )
    args = parser.parse_args()

    try:
        mounted = mounted_prefixes()
    except Exception as exc:  # reported, never swallowed into a pass
        print(f"FAIL: could not import the hive app ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1

    registry = _object(_read(REGISTRY), "prefixes")
    public = set(_object(_read(PUBLIC_REGISTRY), "routes"))
    current = undeclared(mounted, registry, public)
    if args.write_baseline:
        write_baseline(current)
        print(f"wrote {len(current)} undeclared prefix(es) to {BASELINE.relative_to(ROOT)}")
        return 0

    candidate = set(_object(_read(BASELINE), "tolerated"))
    prov = _provenance()
    try:
        prov.require_measurement(mounted, ratchet=RATCHET, what="mounted /v1/ prefixes")
        trusted_ref = prov.resolve_baseline(BASELINE, root=ROOT)
        trusted_payload = trusted_ref.loads(default={})
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=trusted_payload.get("metric_definition_version")
            if isinstance(trusted_payload, dict)
            else None,
            ratchet=RATCHET,
            baseline=trusted_ref,
        )
        trusted = set(_object(trusted_payload, "tolerated"))
        trusted_registry = _object(
            prov.resolve_baseline(REGISTRY, root=ROOT).loads(default={}), "prefixes"
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    exemptions = new_exemptions(registry, trusted_registry)
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="hive app route table",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} tolerated undeclared prefixes",
            new_value=f"{len(current)} undeclared of {len(mounted)} mounted",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{key}: {authorized[key]}"
                for key in sorted((current - trusted) | exemptions)
                if key in authorized
            ),
        ).render()
    )

    failures = registry_problems(mounted, registry, public, date.today())
    failures.extend(compare(current, candidate, trusted, exemptions, set(authorized)))
    if failures:
        print(f"\nFAIL: {len(failures)} route-permission problem(s):\n", file=sys.stderr)
        print("\n".join(f"  - {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"ok: {len(registry)} declared, {len(current)} tolerated undeclared prefix(es), none new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
