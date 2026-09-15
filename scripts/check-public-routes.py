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
import re
import subprocess
import sys
from datetime import date
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MIDDLEWARE = ROOT / "packages" / "hive-conductor" / "backend" / "middleware" / "auth.py"
REGISTRY = ROOT / "quality" / "public-routes.json"
ROUTE_REGISTRY = ROOT / "quality" / "route-permissions.json"
_TURING_MIDDLEWARE = ROOT / "packages" / "maistro-turing" / "backend" / "middleware" / "auth.py"
_ROUTE_POLICY_SOURCE = (
    ROOT / "packages" / "maistro-core" / "src" / "maistro" / "security" / "http_routes.py"
)
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "public-routes"
METRIC_DEFINITION_VERSION = "2"
_GIT_TIMEOUT_SECONDS = 60
_APPLICATIONS = ("conductor", "turing")
_ROUTE_KINDS = frozenset({"exact", "prefix", "template"})
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*$")

DECLARATIONS: dict[str, str] = {
    "_PUBLIC_PREFIXES": "prefix",
    "_PUBLIC_PREFIXES_LOOSE": "loose-prefix",
    "_PUBLIC_EXACT": "exact",
}
REQUIRED = ("kind", "owner", "risk", "disposition", "reason")
REQUIRED_TEMPORARY = ("issue", "expires")
RISKS = frozenset({"low", "medium", "high"})
DISPOSITIONS = frozenset({"permanent", "temporary"})


def _route_policy_matcher() -> Any:
    spec = importlib.util.spec_from_file_location("_http_route_policy", _ROUTE_POLICY_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_ROUTE_POLICY_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.route_policy


route_policy = _route_policy_matcher()


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
        # Merge-group checkouts name an ephemeral
        # refs/heads/gh-readonly-queue/develop/pr-N-<sha> ref that GitHub does
        # not publish for fetch (observed 2026-09-15: every merge-group lint
        # run died here and bounced its whole queue group). Unshallow without
        # a ref filter instead: the unrestricted fetch materializes the queue
        # merge commit's ancestry from the same branches the queue composed
        # it from, which is all this gate needs.
        fallback = _run_git(["fetch", "--no-tags", "--unshallow", "origin"])
        if fallback.returncode != 0:
            raise prov.RatchetProvenanceError(
                f"could not unshallow GitHub event ref {current_ref!r}: "
                f"{fetched.stderr.strip()}; unrestricted fallback also failed: "
                f"{fallback.stderr.strip()}"
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


def _application_registry(loaded: object, application: str) -> dict[str, Any]:
    """Read one public-route declaration without changing the legacy shape."""
    if not isinstance(loaded, dict):
        return {}
    applications = loaded.get("applications")
    if not isinstance(applications, dict):
        return {}
    selected = applications.get(application)
    if not isinstance(selected, dict):
        return {}
    routes = selected.get("routes")
    return dict(routes) if isinstance(routes, dict) else {}


def _registry_identities(registry: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (path, str(entry.get("kind")))
        for path, entry in registry.items()
        if isinstance(entry, dict) and entry.get("kind")
    }


def _route_policy_map(loaded: object) -> dict[tuple[str, str, str, str], tuple[str, str]]:
    """Flatten route policy decisions for trusted-base policy comparisons."""
    if not isinstance(loaded, dict) or not isinstance(loaded.get("routes"), dict):
        return {}
    result: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    for application, entries in loaded["routes"].items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            kind = entry.get("kind")
            methods = entry.get("methods")
            access = entry.get("access")
            if (
                not isinstance(path, str)
                or not isinstance(kind, str)
                or not isinstance(methods, list)
            ):
                continue
            if not isinstance(access, str):
                continue
            permission = entry.get("permission", "")
            permission = permission if isinstance(permission, str) else ""
            for method in methods:
                if isinstance(method, str):
                    result[(str(application), method.upper(), path, kind)] = (access, permission)
    return result


def _route_policy_failures(
    base: dict[tuple[str, str, str, str], tuple[str, str]],
    current: dict[tuple[str, str, str, str], tuple[str, str]],
    authorized: dict[str, str],
) -> list[str]:
    """Permit policy additions while ratcheting existing public/exempt state."""
    failures: list[str] = []
    for key in sorted(set(base) & set(current)):
        if base[key] == current[key]:
            continue
        application, method, path, _kind = key
        grant = f"{application}:{method}:{path}"
        if grant not in authorized:
            failures.append(
                f"  {grant}: route policy changed from {base[key]!r} to {current[key]!r} "
                "without trusted authorization"
            )
    for key in sorted(set(current) - set(base)):
        if current[key][0] not in {"public", "exempt"}:
            continue
        application, method, path, _kind = key
        grant = f"{application}:{method}:{path}"
        if grant not in authorized:
            failures.append(
                f"  {grant}: new {current[key][0]} route policy needs already-landed authorization"
            )
    return failures


def _public_identities_by_application(loaded: object) -> dict[str, set[tuple[str, str]]]:
    """Return public route identities from the trusted legacy registry.

    The application split is important during the first Turing inventory: its
    current declarations are audited now, while later changes are ratcheted
    once the Turing section exists at the trusted base.
    """
    if not isinstance(loaded, dict):
        return {}
    result: dict[str, set[tuple[str, str]]] = {}
    result["conductor"] = _registry_identities(loaded.get("routes", {}))
    applications = loaded.get("applications")
    if isinstance(applications, dict):
        for application in applications:
            result[str(application)] = _registry_identities(
                _application_registry(loaded, str(application))
            )
    return result


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


def audit_turing_public(today: date | None = None) -> list[str]:
    """Audit Turing's public declarations with the same registry rules."""
    declared = declared_paths(_TURING_MIDDLEWARE.read_text(encoding="utf-8"))
    loaded = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return audit_registry(declared, _application_registry(loaded, "turing"), today)


def _route_matches(path: str, declared: str, kind: str) -> bool:
    if kind == "exact":
        return path == declared
    if kind == "prefix":
        boundary = declared.rstrip("/")
        return path == boundary or path.startswith(boundary + "/")
    if kind == "template":
        pattern = re.sub(r"\{[^/{}]+\}", r"[^/]+", declared)
        return re.fullmatch(pattern.rstrip("/"), path.rstrip("/")) is not None
    return False


def _route_identities(route: Any) -> list[tuple[str, str]]:
    """Read one concrete route or FastAPI's flattened included-route context."""
    path = getattr(route, "path", None)
    if not path:
        path = getattr(route, "path_format", None)
    if not path:
        path = getattr(getattr(route, "starlette_route", None), "path", None)
    methods = getattr(route, "methods", ())
    if not isinstance(path, str):
        return []
    method_names = {str(method).upper() for method in (methods or ())}
    if "GET" in method_names:
        # FastAPI registers HEAD as an implementation detail of GET. The route
        # policy declares the application method, not that implicit duplicate.
        method_names.discard("HEAD")
    route_kind = getattr(route, "original_route", route)
    if not method_names and route_kind.__class__.__name__.endswith("WebSocketRoute"):
        method_names = {"WEBSOCKET"}
    return [(method, path) for method in sorted(method_names)]


def registered_routes(app: Any) -> list[tuple[str, str]]:
    """Return concrete identities from the live FastAPI application route tree.

    FastAPI 0.141 keeps included routers as lazy ``_IncludedRouter`` entries in
    ``app.routes``. Its effective contexts are the actual prefixed routes used
    by dispatch; inspecting only the top-level entries would silently reduce
    both applications to their four documentation routes.
    """
    found: list[tuple[str, str]] = []
    for route in getattr(app, "routes", ()):
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            found.extend(
                identity for context in contexts() for identity in _route_identities(context)
            )
            continue
        found.extend(_route_identities(route))
    return sorted(set(found))


def _load_application(application: str) -> Any:
    """Import a production app for route discovery, failing rather than skipping it."""
    if application == "conductor":
        paths = [
            ROOT / "packages" / "hive-conductor" / "backend",
            ROOT / "packages" / "maistro-design" / "src",
            ROOT / "packages" / "maistro-core" / "src",
        ]
        module_name = "main"
    elif application == "turing":
        # Route discovery must not need a deployer's secret, but it must still
        # import the real app. A placeholder is scoped to this checker process.
        os.environ.setdefault("TURING_SERVICE_KEY", "route-discovery-placeholder")
        paths = [
            ROOT / "packages" / "maistro-turing",
            ROOT / "packages" / "maistro-turing" / "src",
            ROOT / "packages" / "maistro-core" / "src",
        ]
        module_name = "backend.main"
    else:  # pragma: no cover - callers use the fixed application tuple
        raise ValueError(f"unknown application {application!r}")

    for path in reversed(paths):
        sys.path.insert(0, str(path))
    try:
        module = import_module(module_name)
        app = getattr(module, "app", None)
        if app is None:
            factory = getattr(module, "create_app", None)
            app = factory() if callable(factory) else None
        if app is None or not hasattr(app, "routes"):
            raise RuntimeError(f"{application} module {module_name!r} did not expose a FastAPI app")
        return app
    except Exception as exc:
        raise RuntimeError(
            f"could not import {application} backend for route discovery: {exc}"
        ) from exc


def _route_entry_failures(  # noqa: C901
    application: str, discovered: list[tuple[str, str]], entries: list[Any], today: date
) -> list[str]:
    failures: list[str] = []
    usable: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            failures.append(f"  {application}[{index}]: route declaration is not an object")
            continue
        path = entry.get("path")
        kind = entry.get("kind")
        if not isinstance(path, str) or not path.startswith("/"):
            failures.append(f"  {application}[{index}]: route declaration needs an absolute path")
        if kind not in _ROUTE_KINDS:
            failures.append(f"  {application}[{index}]: unknown route matching kind {kind!r}")
        methods = entry.get("methods", ["*"])
        if (
            not isinstance(methods, list)
            or not methods
            or any(not isinstance(method, str) for method in methods)
        ):
            failures.append(f"  {application}[{index}]: methods must be a non-empty list")
        usable.append(entry)

    for method, path in discovered:
        matches = [
            entry
            for entry in usable
            if method in entry.get("methods", ["*"]) or "*" in entry.get("methods", ["*"])
            if _route_matches(path, str(entry.get("path", "")), str(entry.get("kind", "")))
        ]
        if not matches:
            failures.append(f"  {application} {method} {path}: registered route has no declaration")
            continue
        # Use the same matcher as both runtime middlewares. Invalid entries
        # were already reported above and are excluded from selection so a
        # malformed policy cannot turn the gate itself into an exception.
        valid_entries = [
            entry
            for entry in usable
            if entry.get("kind") in _ROUTE_KINDS
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("methods", ["*"]), list)
        ]
        selected = route_policy(tuple(valid_entries), method, path)
        if selected is None:
            failures.append(f"  {application} {method} {path}: route declarations are ambiguous")
            continue
        failures.extend(_route_entry_problems(f"{application} {method} {path}", selected, today))

    # A declaration that matches no live route is stale. Stale approvals are
    # dangerous because a later route can accidentally inherit their intent.
    for index, entry in enumerate(usable):
        if not any(
            (method in entry.get("methods", ["*"]) or "*" in entry.get("methods", ["*"]))
            and _route_matches(path, str(entry.get("path", "")), str(entry.get("kind", "")))
            for method, path in discovered
        ):
            failures.append(
                f"  {application}[{index}]: route declaration matches no registered route"
            )
    return failures


def _route_entry_problems(path: str, entry: dict[str, Any], today: date) -> list[str]:
    access = entry.get("access")
    if access == "permission":
        permission = entry.get("permission")
        if not isinstance(permission, str) or _PERMISSION_RE.fullmatch(permission) is None:
            return [f"  {path}: permission must use canonical scope.verb vocabulary"]
        return []
    if access == "public":
        return _entry_problems(path, entry, str(entry.get("kind")), today)
    if access == "exempt":
        missing = [
            f"  {path}: an exemption must name {field!r}"
            for field in ("owner", "reason", "expires")
            if not entry.get(field)
        ]
        if missing:
            return missing
        try:
            expires = date.fromisoformat(str(entry["expires"]))
        except ValueError:
            return [f"  {path}: exemption expires is not a YYYY-MM-DD date"]
        if expires < today:
            return [f"  {path}: exemption expired on {expires.isoformat()}"]
        return []
    return [f"  {path}: access must be permission, public, or exempt"]


def audit_registered_routes(today: date | None = None) -> list[str]:
    """Discover both live apps and audit them against the one route registry."""
    today = today or date.today()
    loaded = json.loads(ROUTE_REGISTRY.read_text(encoding="utf-8"))
    routes = loaded.get("routes") if isinstance(loaded, dict) else None
    if not isinstance(routes, dict):
        return [f"  {ROUTE_REGISTRY.name}: routes must contain both applications"]
    failures: list[str] = []
    for application in _APPLICATIONS:
        entries = routes.get(application)
        if not isinstance(entries, list):
            failures.append(f"  {application}: route registry section is missing")
            continue
        app = _load_application(application)
        failures.extend(_route_entry_failures(application, registered_routes(app), entries, today))
    return failures


def main() -> int:
    for required in (MIDDLEWARE, REGISTRY, ROUTE_REGISTRY, _TURING_MIDDLEWARE):
        if not required.is_file():
            print(f"FAIL: {required} does not exist", file=sys.stderr)
            return 1

    declared_by_application = {
        "conductor": declared_paths(MIDDLEWARE.read_text(encoding="utf-8")),
        "turing": declared_paths(_TURING_MIDDLEWARE.read_text(encoding="utf-8")),
    }
    declared = {
        f"{application}:{path}:{kind}"
        for application, paths in declared_by_application.items()
        for path, kind in paths.items()
    }
    loaded_public = json.loads(REGISTRY.read_text(encoding="utf-8"))
    candidate = _registry(loaded_public)
    candidate_failures = audit_registry(declared_by_application["conductor"], candidate)
    candidate_failures.extend(
        audit_registry(
            declared_by_application["turing"],
            _application_registry(loaded_public, "turing"),
        )
    )
    try:
        candidate_failures.extend(audit_registered_routes())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        candidate_failures.append(f"  route discovery failed closed: {exc}")

    prov = _provenance()
    route_policy_failures: list[str] = []
    route_base_ref = None
    try:
        _materialize_ci_history(prov)
        base_ref = prov.resolve_baseline(REGISTRY, root=ROOT)
        base_loaded = base_ref.loads(default={"routes": {}})
        base_registries = _public_identities_by_application(base_loaded)
        prov.require_measurement(declared, ratchet=RATCHET, what="public routes")
        authorized = prov.load_authorizations(RATCHET, base=base_ref.base_sha)
        # Permission policy is also trusted-base state. Public-surface growth
        # uses the public-routes ratchet above; this second comparison prevents
        # a candidate from weakening an existing protected/exempt declaration
        # by editing the route table and its consumer together.
        route_base_ref = prov.resolve_baseline(ROUTE_REGISTRY, root=ROOT)
        if not route_base_ref.absent_at_base:
            route_authorized = prov.load_authorizations(
                "route-permissions", base=route_base_ref.base_sha
            )
            route_policy_failures.extend(
                _route_policy_failures(
                    _route_policy_map(route_base_ref.loads(default={})),
                    _route_policy_map(json.loads(ROUTE_REGISTRY.read_text(encoding="utf-8"))),
                    route_authorized,
                )
            )
    except (RuntimeError, prov.RatchetProvenanceError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    # The Turing public table is bootstrapped by this issue. Once it exists at
    # the trusted base, the same identity ratchet applies to it automatically.
    current_identities = {
        (application, path, kind)
        for application, paths in declared_by_application.items()
        if application in base_registries
        for path, kind in paths.items()
    }
    base_identities = {
        (application, path, kind)
        for application, identities in base_registries.items()
        for path, kind in identities
    }
    added_identities = sorted(current_identities - base_identities)
    # Tightening FastAPI's historical loose /openapi matcher to its one
    # registered schema route is a narrowing, not a newly public surface.
    added_identities = [
        identity
        for identity in added_identities
        if not (
            (
                identity[0] == "conductor"
                and identity[1] == "/openapi.json"
                and identity[2] == "exact"
                and ("/openapi", "loose-prefix") in base_registries.get("conductor", set())
            )
            or (
                identity[0] == "conductor"
                and identity[2] == "prefix"
                and identity[1] in {"/docs", "/redoc"}
                and (identity[1], "loose-prefix") in base_registries.get("conductor", set())
            )
        )
    ]
    affected_paths = sorted(
        {f"{application}:{path}" for application, path, _kind in added_identities}
    )
    unauthorized = [path for path in affected_paths if path not in authorized]
    unbanked_authorized = [
        path
        for path in affected_paths
        if path in authorized
        and not any(candidate_path == path.partition(":")[2] for candidate_path in candidate)
    ]

    if route_base_ref is not None and not route_base_ref.absent_at_base:
        print(
            prov.Provenance(
                ratchet="route-permissions",
                baseline=route_base_ref,
                tool="shared route policy",
                metric_definition_version=METRIC_DEFINITION_VERSION,
                old_value="trusted route policy",
                new_value="candidate route policy",
                candidate_sha=prov.head_sha(ROOT),
            ).render()
        )

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=base_ref,
            tool="python ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(base_identities)} public route identities",
            new_value=f"{len(current_identities)} public route identities",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{path}: {authorized[path]}" for path in affected_paths if path in authorized
            ),
        ).render()
    )

    failures = [*candidate_failures, *route_policy_failures]
    for path in unauthorized:
        application, _, route_path = path.partition(":")
        base_entry = base_registries.get(application, set())
        old_kind = next(
            (kind for candidate_path, kind in base_entry if candidate_path == route_path),
            None,
        )
        if old_kind is None:
            failures.append(
                f"  {path}: NEW unauthenticated path is absent from the trusted base and has no "
                "already-landed authorization"
            )
        else:
            failures.append(
                f"  {path}: unauthenticated matching kind changed from {old_kind!r} to "
                f"{next((kind for candidate_path, kind in declared_by_application[application].items() if candidate_path == route_path), None)!r} "
                "without already-landed authorization"
            )
    failures.extend(
        f"  {path}: authorized public-surface expansion is not recorded in the candidate registry"
        for path in unbanked_authorized
    )

    if failures:
        print(f"FAIL: {len(failures)} problem(s) with the HTTP route authorization surface:\n")
        print("\n".join(failures))
        print(
            "\nA new public route or matching-kind expansion requires its registry entry plus a "
            "separately landed authorization. Existing entries remain ordinary reviewed policy "
            "and must stay owned, justified, correctly shaped, and unexpired."
        )
        return 1

    print(
        f"ok: all {len(declared)} unauthenticated path(s) are declared and base-authorized; "
        "both live route tables are declared and authorized"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
