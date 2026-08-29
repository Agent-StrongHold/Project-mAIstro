#!/usr/bin/env python3
"""Gate: every path that skips authentication is declared, owned, and justified
(#316).

Why this exists
---------------
`/v1/voice/` sat in `AuthMiddleware`'s `_PUBLIC_PREFIXES` for the whole of this
repository's history. It is one string in one tuple, it reads exactly like the
`/health` above it, and it made an entire prefix — including a route that
reaches the tool loop — answer to anyone who could send it a request. The
route's own optional key could not close it: unset was the shipped default, and
unset meant "return early".

The lesson is not "review tuples more carefully". It is that adding a public
route costs one line and reviewing it costs reading the whole handler chain
behind it, so the two are never in balance. This puts the decision somewhere it
has to be argued: a path is public only if `quality/public-routes.json` says
who owns it, what it exposes, and whether the exemption is permanent or has a
date by which it must be re-justified.

Both directions are checked. A path in the middleware and not the registry
fails — that is a bypass nobody signed. A path in the registry and not the
middleware fails too — a stale entry is a pre-approval waiting for whoever next
adds that string back.

What "expiry" means
-------------------
A `temporary` exemption names the issue that removes it and a date. The date is
not a promise that the work lands by then; it is the point at which the
exemption stops being self-approving and someone has to look again. Past it,
this gate fails and names the issue.

Usage
-----
    python3 scripts/check-public-routes.py
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MIDDLEWARE = ROOT / "packages" / "hive-conductor" / "backend" / "middleware" / "auth.py"
REGISTRY = ROOT / "quality" / "public-routes.json"
RATCHET = "public-routes"
METRIC_DEFINITION_VERSION = "1"

#: Loaded by path, and registered in `sys.modules` before execution: this
#: script is itself loaded with `spec_from_file_location` by its tests, which
#: puts nothing on `sys.path` for a sibling import, and `@dataclass` resolves
#: field types through `sys.modules[cls.__module__]`.
_PROVENANCE_SOURCE = Path(__file__).resolve().parent / "ratchet_provenance.py"


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: Module-level names in `auth.py` holding public paths, and the `kind` a
#: registry entry must declare for a path found in each. The kinds are distinct
#: because they match differently: `prefix` is boundary-safe (`/health` does not
#: match `/healthz`), `loose-prefix` is a bare `startswith`, and `exact` is one
#: path. Recording which one a route got means the registry describes the
#: exemption that exists rather than the one the author had in mind.
DECLARATIONS: dict[str, str] = {
    "_PUBLIC_PREFIXES": "prefix",
    "_PUBLIC_PREFIXES_LOOSE": "loose-prefix",
    "_PUBLIC_EXACT": "exact",
}

#: Fields every entry carries, whatever its disposition.
REQUIRED = ("kind", "owner", "risk", "disposition", "reason")

#: Extra fields a `temporary` exemption carries. A permanent one has no issue
#: to name and no date to be re-justified by.
REQUIRED_TEMPORARY = ("issue", "expires")

RISKS = frozenset({"low", "medium", "high"})
DISPOSITIONS = frozenset({"permanent", "temporary"})


def declared_paths(source: str) -> dict[str, str]:
    """`{path: kind}` for every literal in the declarations above.

    Read from the syntax tree rather than by importing `auth.py`, which pulls
    in FastAPI and the whole backend package layout; a gate that needs the
    application to import in order to run is a gate that stops running the
    first time the application does not.
    """
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
    """Field-level problems: wrong kind, unknown risk, unknown disposition."""
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
    """Problems with a `temporary` exemption's issue and date."""
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
    """Everything wrong with one registry entry, as messages."""
    if not isinstance(entry, dict):
        return [f"  {path}: registry entry is not an object"]

    missing = [f"  {path}: missing {field!r}" for field in REQUIRED if not entry.get(field)]
    if missing:
        return missing

    problems = _shape_problems(path, entry, kind)
    if problems or entry["disposition"] != "temporary":
        return problems
    return _expiry_problems(path, entry, today)


def trusted_registry(base: str | None = None) -> tuple[dict[str, Any] | None, Any]:
    """The registry as of the base revision, and where that was.

    Its own function so a test can substitute the trusted state without
    standing up a git history -- the same reason `REGISTRY` is a module global
    rather than a default argument.
    """
    prov = _provenance()
    baseline = prov.resolve_baseline(REGISTRY, base=base, root=ROOT)
    loaded = baseline.loads(default=None)
    if loaded is None:
        return None, baseline
    return loaded.get("routes", {}), baseline


def audit(
    today: date | None = None,
    trusted: dict[str, Any] | None = None,
    authorized: dict[str, str] | None = None,
) -> list[str]:
    """One message per disagreement between the middleware and the registry.

    `trusted` is the registry as of the base revision. Without it this is the
    consistency check it always was -- the middleware and the registry agree --
    which proves that whoever exposed the route also wrote it down, and nothing
    about whether anyone else agreed. With it, a path that is public now and was
    not declared at the base is a *new* unauthenticated surface, and needs a
    grant that landed before this change (#542 group 2).
    """
    today = today or date.today()
    declared = declared_paths(MIDDLEWARE.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8")).get("routes", {})
    authorized = authorized or {}

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
        if trusted is not None and path not in trusted and path not in authorized:
            failures.append(
                f"  {path}: newly public, and the registry did not carry it at the base. "
                "Exposing a route and signing for it in one commit is one act by one "
                "author; record the grant in quality/ratchet-authorizations.json under "
                f"'{RATCHET}' so it lands before the route does"
            )

    for path in sorted(set(registry) - set(declared)):
        failures.append(
            f"  {path}: declared in {REGISTRY.name} and not public in "
            f"{MIDDLEWARE.name} — a stale entry pre-approves whoever adds it back"
        )
    return failures


def main() -> int:
    for required in (MIDDLEWARE, REGISTRY):
        if not required.is_file():
            print(f"FAIL: {required} does not exist", file=sys.stderr)
            return 1

    prov = _provenance()
    try:
        trusted, baseline = trusted_registry()
        # The same revision the registry came from, named rather than resolved
        # a second time: two resolutions of "the base" can disagree, and a
        # grant read from one commit permitting a route measured against
        # another is not the check it looks like.
        authorized = prov.load_authorizations(RATCHET, base=baseline.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    failures = audit(trusted=trusted, authorized=authorized)
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=baseline,
            tool="ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted or {})} public path(s) declared",
            new_value=f"{len(declared_paths(MIDDLEWARE.read_text(encoding='utf-8')))} public",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(f"{k}: {v}" for k, v in sorted(authorized.items())),
        ).render()
    )
    if failures:
        print(f"FAIL: {len(failures)} problem(s) with the unauthenticated route surface:\n")
        print("\n".join(failures))
        print(
            "\nMaking a route public costs one line; reviewing it costs reading "
            "\neverything behind it. quality/public-routes.json is where that "
            "\nasymmetry gets an owner, a risk, and — for anything meant to be "
            "\ntemporary — a date by which it stops approving itself."
        )
        return 1

    count = len(declared_paths(MIDDLEWARE.read_text(encoding="utf-8")))
    print(f"ok: all {count} unauthenticated path(s) are declared, owned, and unexpired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
