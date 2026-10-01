#!/usr/bin/env python3
"""Ratchet authenticated Conductor route prefixes (Workspace cutover P0.2 / #53 AC-P2).

Every ``/v1/{segment}`` prefix mounted on the hive app must appear in
``quality/route-permissions.json`` with either:

  * a ``permission`` (``scope.verb`` vocabulary), or
  * an ``exempt_reason`` plus ``owner``, ``disposition``, and for temporary
    exemptions ``issue`` + ``expires``

Public paths (declared in ``quality/public-routes.json`` / auth middleware) are
out of scope — this gate covers authenticated surface only.

Baseline: ``quality/route-permissions-baseline.json``. New undeclared prefixes
fail CI; fixed prefixes must drop their baseline row. The comparison ledger is
resolved from the trusted base revision (``scripts/ratchet_provenance.py``),
not the candidate tree: a commit that added a gap and the baseline row blessing
it in the same change could otherwise approve its own regression (#542, #319).
The worktree copy remains the bookkeeping oracle — a row naming a gap that no
longer exists must be pruned.

Run: ``python scripts/check-route-permissions.py``
Bank: ``python scripts/check-route-permissions.py --write-baseline``
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "quality" / "route-permissions.json"
BASELINE = ROOT / "quality" / "route-permissions-baseline.json"
PUBLIC_REGISTRY = ROOT / "quality" / "public-routes.json"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"

REQUIRED = ("owner", "disposition", "reason")
REQUIRED_PERMISSION = ("permission", *REQUIRED)
REQUIRED_EXEMPT = ("exempt_reason", *REQUIRED)
REQUIRED_TEMPORARY = ("issue", "expires")
DISPOSITIONS = frozenset({"permanent", "temporary"})


@dataclass(frozen=True)
class Gap:
    prefix: str
    detail: str

    def key(self) -> str:
        return self.prefix


def _v1_prefix(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) >= 3 and parts[1] == "v1" and parts[2]:
        return f"/v1/{parts[2]}"
    return None


def _collect_prefixes() -> tuple[set[str], str | None]:
    backend = ROOT / "packages" / "hive-conductor" / "backend"
    if not backend.is_dir():
        return set(), "hive-conductor backend not present"

    for src_root in sorted((ROOT / "packages").glob("*/src")):
        sys.path.insert(0, str(src_root))
    sys.path.insert(0, str(backend))
    os.environ.setdefault("CONDUCTOR_DATA_DIR", "/tmp/route-perm-check-data")
    try:
        from main import app  # type: ignore[import-not-found]

        from maistro_server.api.route_table import iter_effective_routes
    except Exception as exc:  # pragma: no cover - reported, never swallowed
        return set(), f"could not import the app ({type(exc).__name__}: {exc})"

    prefixes: set[str] = set()
    for route in iter_effective_routes(app.routes):
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        prefix = _v1_prefix(path)
        if prefix is not None:
            prefixes.add(prefix)
    return prefixes, None


def _public_paths() -> set[str]:
    if not PUBLIC_REGISTRY.is_file():
        return set()
    loaded = json.loads(PUBLIC_REGISTRY.read_text(encoding="utf-8"))
    routes = loaded.get("routes")
    if not isinstance(routes, dict):
        return set()
    return {str(path) for path in routes}


def _load_registry() -> dict[str, Any]:
    if not REGISTRY.is_file():
        return {}
    loaded = json.loads(REGISTRY.read_text(encoding="utf-8"))
    prefixes = loaded.get("prefixes")
    return dict(prefixes) if isinstance(prefixes, dict) else {}


def _entry_problems(prefix: str, entry: Any, today: date) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{prefix}: registry entry is not an object"]
    has_permission = bool(entry.get("permission"))
    has_exempt = bool(entry.get("exempt_reason"))
    if has_permission == has_exempt:
        return [
            f"{prefix}: declare exactly one of 'permission' or 'exempt_reason', not "
            f"{'both' if has_permission else 'neither'}"
        ]
    required = REQUIRED_PERMISSION if has_permission else REQUIRED_EXEMPT
    missing = [f"{prefix}: missing {field!r}" for field in required if not entry.get(field)]
    if missing:
        return missing
    if entry.get("disposition") not in DISPOSITIONS:
        return [f"{prefix}: disposition must be one of {sorted(DISPOSITIONS)}"]
    if entry.get("disposition") == "temporary":
        missing_temp = [
            f"{prefix}: temporary exemption must name {field!r}"
            for field in REQUIRED_TEMPORARY
            if not entry.get(field)
        ]
        if missing_temp:
            return missing_temp
        try:
            expires = date.fromisoformat(str(entry["expires"]))
        except ValueError:
            return [f"{prefix}: expires {entry['expires']!r} is not YYYY-MM-DD"]
        if expires < today:
            return [f"{prefix}: exemption expired on {expires.isoformat()}"]
    return []


def collect_gaps(today: date | None = None) -> tuple[list[Gap], str | None]:
    today = today or date.today()
    prefixes, import_error = _collect_prefixes()
    if import_error is not None:
        return [], import_error

    registry = _load_registry()
    public = _public_paths()
    gaps: list[Gap] = []
    for prefix in sorted(prefixes):
        if prefix in public:
            continue
        entry = registry.get(prefix)
        if entry is None:
            gaps.append(Gap(prefix, "authenticated prefix absent from route-permissions.json"))
            continue
        problems = _entry_problems(prefix, entry, today)
        if problems:
            gaps.append(Gap(prefix, "; ".join(problems)))
    for prefix in sorted(set(registry) - prefixes):
        gaps.append(Gap(prefix, "declared in registry but not mounted on the app"))
    return gaps, None


def _provenance() -> Any:
    """Load the shared trusted-base resolver (``scripts/ratchet_provenance.py``)."""
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


def _load_tolerated(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    tolerated = payload.get("tolerated")
    if not isinstance(tolerated, dict):
        return {}
    return {str(key): str(value) for key, value in tolerated.items()}


def _load_baseline() -> dict[str, str]:
    """Candidate ledger (worktree): the bookkeeping oracle for stale-row pruning."""
    if not BASELINE.is_file():
        return {}
    return _load_tolerated(json.loads(BASELINE.read_text(encoding="utf-8")))


def _trusted_baseline() -> dict[str, str]:
    """Ledger at the merge base: the oracle NEW gaps are judged against."""
    ref = _provenance().resolve_baseline(BASELINE, root=ROOT)
    return _load_tolerated(ref.loads(default={"tolerated": {}}))


def audit() -> tuple[list[Gap], list[str], list[str], str | None]:
    gaps, import_error = collect_gaps()
    if import_error is not None:
        return [], [], [], import_error
    trusted = _trusted_baseline()
    candidate = _load_baseline()
    current = {item.key(): item.detail for item in gaps}
    new_keys = sorted(set(current) - set(trusted))
    stale_keys = sorted(set(candidate) - set(current))
    new_gaps = [item for item in gaps if item.key() in new_keys]
    return new_gaps, stale_keys, sorted(candidate.keys()), None


def write_baseline(gaps: list[Gap]) -> None:
    payload = {
        "_comment": (
            "Undeclared authenticated route prefixes for P0.2. New gaps fail CI; "
            "fixed gaps must delete their row."
        ),
        "tolerated": {item.key(): item.detail for item in gaps},
    }
    BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _audit_or_fail() -> tuple[list[Gap], list[str], list[str], str | None] | None:
    """``audit()``, rendering a trusted-base provenance failure as a FAIL line."""
    prov = _provenance()
    try:
        return audit()
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return None


def _print_tolerated(tolerated_keys: list[str]) -> None:
    if not tolerated_keys:
        return
    print(f"tolerated (baselined): {len(tolerated_keys)}")
    for key in tolerated_keys[:10]:
        print(f"  · {key}")
    if len(tolerated_keys) > 10:
        print(f"  · … and {len(tolerated_keys) - 10} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current gap set as the tolerated baseline",
    )
    args = parser.parse_args()

    gaps, import_error = collect_gaps()
    if import_error is not None:
        print(f"FAIL: {import_error}", file=sys.stderr)
        return 1

    if args.write_baseline:
        write_baseline(gaps)
        print(f"wrote {len(gaps)} tolerated gap(s) to {BASELINE.relative_to(ROOT)}")
        return 0

    audited = _audit_or_fail()
    if audited is None:
        return 1
    new_gaps, stale_keys, tolerated_keys, import_error = audited
    if import_error is not None:
        print(f"FAIL: {import_error}", file=sys.stderr)
        return 1

    print(f"scanned authenticated /v1/ prefixes: {len(gaps)} current gap(s)")
    _print_tolerated(tolerated_keys)

    failures: list[str] = []
    if new_gaps:
        failures.extend(f"NEW  {item.key()}: {item.detail}" for item in new_gaps)
    if stale_keys:
        failures.extend(f"STALE {key} (fixed — delete from baseline)" for key in stale_keys)

    if failures:
        print(f"\nFAIL: {len(failures)} route-permission ratchet problem(s):\n")
        print("\n".join(failures))
        return 1

    print("ok: no new route-permission gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
