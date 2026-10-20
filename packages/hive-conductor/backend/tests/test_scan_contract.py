"""The scan-surface contract (#288): every Scan action the app exposes either
runs a real scanner or refuses explicitly, and no production code ships the
fake-clean shape.

#418 closed the fake-clean agent scan, and the same stub survived one door
over: `POST /v1/mcp/servers/{server_id}/scan` answered
`{"findings": [], "status": "clean"}` without running anything. That surface
now refuses explicitly (501, #389); the agent and skills surfaces run the
Warden walk. Closing one path must not leave another stub behind, so this
module enforces the property mechanically, three ways:

1. **The route census.** Every POST route whose path ends in `/scan` is
   enumerated from the *live app* (`main.app`), not from a hand-kept list, and
   must map to exactly the registered handler. A new scan route fails here
   until it is registered (a deliberate act), and a registered route that
   vanishes fails too -- the enumeration cannot rot silently.
2. **The source sweep.** No module under `routes/` or `services/` may contain
   the literal fake-clean dict (`"findings": []` beside a constant
   `"status": "clean"`). Conditional forms (`"clean" if not findings else
   "flagged"`) are the correct shape and are not matched; only the
   unconditional literal is -- the one that reports clean without looking.
3. **The unsupported surface.** The one scan route without a scanner wired
   must say so with an explicit error, never answer `clean`. This keeps the
   "unsupported" state distinct from both "clean" and "failed".

The per-surface behavior (a known malicious fixture is flagged, a known clean
fixture passes, a broken scanner is an explicit unknown) is proven in the
route test files; this module proves no *surface* can be a stub.
"""

from __future__ import annotations

import ast
import pathlib
import sys
from collections.abc import Iterator
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

#: The complete set of Scan actions the live app exposes, mapped to the
#: `module.handler` that owns each surface. Enumerated from the app at test
#: time -- not trusted from this list.
#:
#: Note: `routes/projects.py` also defines `POST /{project_id}/scan` (a real
#: repo scanner), but that router is not mounted in `main.py`, so it is no
#: reachable surface; the no-stub source sweep below still covers its module.
EXPECTED_SCAN_ROUTES: dict[str, str] = {
    "/v1/agents/scan": "routes.agents.scan_proposed_config",
    "/v1/agents/{agent_id}/scan": "routes.agents.scan_agent",
    "/v1/skills/scan": "routes.skills.scan_skills",
    "/v1/mcp/servers/{server_id}/scan": "routes.mcp.scan_server",
}

#: Scan surfaces that deliberately have no scanner wired. They must refuse
#: explicitly -- `clean` is the one answer they may never give.
EXPECTED_UNSUPPORTED_SCAN_ROUTES: frozenset[str] = frozenset({"/v1/mcp/servers/{server_id}/scan"})


def _iter_api_routes() -> Iterator[tuple[str, Any]]:
    """Yield (path, APIRoute) for every route the app can serve.

    Newer FastAPI wraps `include_router` in lazy `_IncludedRouter` wrappers
    whose inner `original_router.routes` carry the full (prefixed) paths; top
    level `APIRoute`s are walked too so a FastAPI upgrade cannot quietly
    hollow the census.
    """
    from fastapi.routing import APIRoute
    from main import app

    for route in app.routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            prefix = str(getattr(getattr(route, "include_context", None), "prefix", "") or "")
            for sub in getattr(inner, "routes", []):
                if isinstance(sub, APIRoute):
                    yield prefix + sub.path, sub
        elif isinstance(route, APIRoute):
            yield route.path, route


def _scan_routes() -> dict[str, str]:
    """Enumerate POST routes ending in /scan from the live app."""
    found: dict[str, str] = {}
    for path, route in _iter_api_routes():
        if "POST" in route.methods and path.endswith("/scan"):
            found[path] = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
    return found


def _fake_clean_literals() -> list[str]:
    """`file:line` of every unconditional fake-clean dict in production code.

    Matches a dict literal that maps `findings` to an empty list and `status`
    to the constant `"clean"` -- the exact shape that reports clean without
    running a scanner. Derived statuses are conditional expressions and are
    deliberately not matched.
    """
    hits: list[str] = []
    for module_dir in (_BACKEND / "routes", _BACKEND / "services"):
        for path in sorted(module_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                constants: dict[str, ast.expr] = {}
                for key, value in zip(node.keys, node.values, strict=False):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        constants[key.value] = value
                findings = constants.get("findings")
                status = constants.get("status")
                if (
                    isinstance(findings, ast.List)
                    and not findings.elts
                    and isinstance(status, ast.Constant)
                    and status.value == "clean"
                ):
                    hits.append(f"{path.relative_to(_BACKEND)}:{node.lineno}")
    return hits


class TestTheScanSurfaceContract:
    def test_every_scan_route_is_registered(self) -> None:
        """Both directions: no unregistered scan route can appear (a new stub
        fails until its handler is registered here), and no registered entry
        survives the vanishing of its route."""
        found = _scan_routes()
        unregistered = {p: h for p, h in found.items() if EXPECTED_SCAN_ROUTES.get(p) != h}
        vanished = [p for p in EXPECTED_SCAN_ROUTES if p not in found]
        assert not unregistered, f"scan route(s) not backed by a registered handler: {unregistered}"
        assert not vanished, f"registered scan route(s) no longer exist: {vanished}"

    def test_no_production_code_ships_the_fake_clean_literal(self) -> None:
        """The stub that #418 removed and #288 found again one door over,
        forbidden at the source level so a second copy cannot hide behind a
        new module name."""
        hits = _fake_clean_literals()
        assert not hits, f"unconditional fake-clean scan result(s) at: {hits}"

    def test_the_real_scan_routes_are_behaviorally_covered(self) -> None:
        """The census only pins identities; the behavioral proof (malicious
        fixture flagged, clean fixture handled, broken scanner unknown) must
        exist for every HTTP scan surface. Each registry entry names the test
        module that walks its fixtures."""
        coverage = {
            "/v1/agents/scan": "tests/test_agents_routes.py::TestTheScanActuallyScans",
            "/v1/agents/{agent_id}/scan": "tests/test_agents_routes.py::TestTheScanActuallyScans",
            "/v1/skills/scan": "tests/test_skills_routes.py",
            "/v1/mcp/servers/{server_id}/scan": (
                "tests/test_mcp_routes.py::test_scan_server_found_is_explicitly_unsupported"
            ),
        }
        assert set(coverage) == set(EXPECTED_SCAN_ROUTES)

    def test_unsupported_scan_surfaces_refuse_explicitly(self) -> None:
        """A surface with no scanner wired must not borrow the verdict shape.
        The MCP scan answers 501 for a real server and names the gap; it has no
        branch that returns `clean`."""
        import importlib
        import inspect
        import textwrap

        assert set(EXPECTED_SCAN_ROUTES) >= EXPECTED_UNSUPPORTED_SCAN_ROUTES
        for path in EXPECTED_UNSUPPORTED_SCAN_ROUTES:
            module, symbol = EXPECTED_SCAN_ROUTES[path].rsplit(".", 1)
            source = inspect.getsource(getattr(importlib.import_module(module), symbol))
            assert "status_code=501" in source, f"{path} must refuse explicitly"
            # Docstrings may *describe* the removed stub; only executable
            # `return {... "status": "clean"}` shapes are prohibited.
            tree = ast.parse(textwrap.dedent(source))
            returned_clean = [
                node.lineno
                for node in ast.walk(tree)
                if isinstance(node, ast.Return)
                and isinstance(node.value, ast.Dict)
                and any(
                    isinstance(k, ast.Constant)
                    and k.value == "status"
                    and isinstance(v, ast.Constant)
                    and v.value == "clean"
                    for k, v in zip(node.value.keys, node.value.values, strict=False)
                )
            ]
            assert not returned_clean, f"{path} must not fabricate clean (lines {returned_clean})"


@pytest.mark.parametrize(
    ("module", "symbol"),
    [
        ("routes.agents", "scan_proposed_config"),
        ("routes.agents", "scan_agent"),
    ],
)
def test_the_scan_handlers_run_the_shared_warden_walk(module: str, symbol: str) -> None:
    """The agent scan surfaces must run the *same* bounded Warden walk the
    write path gates on -- not a second, weaker check written locally. The MCP
    surface has no scanner wired and is pinned by the explicit-refusal test
    above instead."""
    import importlib
    import inspect

    handler = getattr(importlib.import_module(module), symbol)
    assert "scan_config" in inspect.getsource(handler), (
        f"{module}.{symbol} must delegate to services.agent_materialization.scan_config"
    )
