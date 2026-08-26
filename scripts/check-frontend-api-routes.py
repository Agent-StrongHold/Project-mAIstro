#!/usr/bin/env python3
"""Gate: every API path the frontend calls is a route the backend registers (#295).

What it catches
---------------
`packages/hive-conductor/frontend/src/pages/ToolsLab.tsx` called
`/v1/tools-lab/status`, `/v1/tools-lab/{id}/start` and `/v1/tools-lab/{id}/stop`.
No `tools-lab` router was ever registered. The page shipped with four tool
cards, a Launch button on each, and a status badge -- all of it driven by a
hardcoded array, because `fetch` does not reject on a 404 and every call site
either guarded on `r.ok` or swallowed the result.

That is why a 404 is not self-announcing here. The browser records it and the
page reports "Starting..." indefinitely; no test fails, no log fires, and the
control looks like it works. The only reliable moment to notice is now.

How it decides
--------------
The backend's answer comes from the app itself -- `main.app.routes`, the same
table Starlette matches real requests against -- not from reading `main.py` for
`include_router` calls. A prefix list would say `/v1/agents` exists and stay
silent about `/v1/agents/forge`; the route table knows the difference.

The frontend's side is read statically, because the alternative is running the
SPA and clicking everything.

A frontend `${expr}` segment matches any one route segment, and a route
`{param}` matches any one frontend segment. Both directions are needed: the
frontend interpolates ids into paths, and the backend names them.

Why an incomplete route table is refused
----------------------------------------
Four routers are optional (`routes.design`, `routes.canvas`, `routes.evolution`,
`routes.rsi`); each is mounted inside a `try`, so a missing dependency drops its
routes silently. Checked against a table missing one, every call the Design page
makes would be reported as an unregistered route -- the true cause being an
import error one layer down. So this reads `app.state.optional_routers` and
refuses to answer at all if any of them failed, rather than answering wrongly.

The escape hatch
----------------
`# frontend-api-routes: allow <reason>` on the calling line or the line above.
Mandatory reason. For a path served by something other than this app -- a
sidecar, a proxy rule, a dev-only mock.

Usage
-----
    PYTHONPATH=packages/hive-conductor/backend:... \\
      python3 scripts/check-frontend-api-routes.py
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "packages" / "hive-conductor" / "frontend" / "src"
BACKEND = REPO_ROOT / "packages" / "hive-conductor" / "backend"

#: Paths the frontend asks for, as they appear in a string or template literal.
#: Anchored to a quote so a path inside a comment or a markdown string is not
#: mistaken for a call site.
CALL_RE = re.compile(r"""["'`](?P<path>/v1/[^"'`\s?#]*)""")

#: `const API = "/v1/evolution"` -- a base a file composes its calls from.
#: Resolved rather than treated as a call, because it is not one: the requests
#: are `${API}/status`, `${API}/population`. Left unresolved, the base reports
#: as an unregistered path (nothing is mounted at `/v1/evolution` itself) and
#: the eight real calls built from it stay invisible -- the wrong answer twice.
BASE_RE = re.compile(
    r"""(?:const|let|var)\s+(?P<name>\w+)\s*=\s*["'`](?P<path>/v1/[^"'`\s]*)["'`]"""
)

#: A call composed from such a base: `${API}/status`.
COMPOSED_RE = re.compile(r"""`\$\{(?P<name>\w+)\}(?P<rest>/[^`]*)`""")

#: A base handed to a caller whole: `fetch(API)`, `apiGet<T>(API)` (#295 review).
#: Without this the binding line is skipped as "not a call" and the direct use
#: produces nothing, so an unregistered base passes as long as the file
#: contains some other measured call.
DIRECT_RE = re.compile(
    r"""\b(?:fetch|api[A-Z]\w*)\s*(?:<[^(]*>)?\(\s*(?P<name>[A-Z_][A-Z0-9_]*)\s*[,)]"""
)

#: The frontend's API helpers name their verb. `apiGet` is the read; the rest
#: write. A helper this does not know leaves the verb unread rather than
#: assumed.
HELPER_VERBS = {
    "apiGet": "GET",
    "apiPost": "POST",
    "apiPut": "PUT",
    "apiPatch": "PATCH",
    "apiDelete": "DELETE",
}
HELPER_RE = re.compile(r"\b(?P<helper>api(?:Get|Post|Put|Patch|Delete))\b")

#: `{ method: "POST" }` in a fetch options object.
METHOD_RE = re.compile(r"""method:\s*["'`](?P<verb>[A-Za-z]+)["'`]""")

#: A well-formed interpolation: `${id}`, `${item.id}`. Deliberately refuses
#: nested braces and backticks, because `${qs ? `?${qs}` : ""}` is a *query
#: string* appended to a path, not a path segment, and treating it as one would
#: invent a segment that is never requested.
INTERPOLATION_RE = re.compile(r"\$\{[^{}`]*\}")

#: The start of any interpolation, well-formed or not.
INTERPOLATION_START = "${"

WAIVER = re.compile(r"#\s*frontend-api-routes:\s*allow\s+(?P<reason>\S.*)")
#: TS/TSX comment form of the same marker, since these are not Python files.
WAIVER_TS = re.compile(r"//\s*frontend-api-routes:\s*allow\s+(?P<reason>\S.*)")

_SKIP_PARTS = {"node_modules", "dist", "build", "__pycache__", ".vite"}

#: One frontend segment that is an interpolation, normalised. Kept distinct from
#: a route's `{param}` so the matcher can tell which side is the wildcard.
WILDCARD = "\x00"


@dataclass(frozen=True)
class Call:
    source: str
    line_no: int
    path: str
    """As written, for the report."""

    method: str | None = None
    """The HTTP verb, when it can be read; None means "any".

    A path match alone is not enough: `GET /v1/chat/complete` reaches a
    POST-only route, Starlette answers 405, and the control is exactly as
    broken as if nothing were registered (#295 review). Read from the helper
    verb (`apiPost`), from an explicit `{ method: "PUT" }`, or defaulted to GET
    for a bare `fetch`. Unreadable stays None rather than guessing, because a
    wrong verb here is a false finding.
    """

    prefix_only: bool = False
    """True when the tail could not be resolved, so only a prefix claim is made.

    Two idioms produce it, and both are everywhere in this frontend:

        apiGet(`/v1/audit${qs ? `?${qs}` : ""}`)   // nested, unparseable
        const API = "/v1/evolution"                 // a base, composed elsewhere

    A static reader cannot follow either to the full path. It can still say
    what the leading segments are, and that is enough for the defect this gate
    exists for -- `/v1/tools-lab` was not the prefix of any registered route,
    so no amount of unknown tail could have made those calls resolve.
    """


@dataclass(frozen=True)
class Finding:
    call: Call

    def render(self) -> str:
        how = " (as a prefix)" if self.call.prefix_only else ""
        return f"  {self.call.source}:{self.call.line_no}\n    {self.call.path}{how}"


def _segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def parse(raw: str) -> tuple[list[str], bool]:
    """`(segments, prefix_only)` for one captured literal.

    **Adjacency decides what an interpolation is.** One that occupies a whole
    segment -- preceded by `/`, ending the path or followed by `/` -- is an id,
    and becomes a wildcard segment. One glued to the end of a segment is a
    suffix, almost always a query string, and truncates the path there.

    Measured on the real frontend, because the first version got this wrong
    (#295 review). `/v1/optimizer/proposals${query}`, where `query` is `""` or
    `"?decision=..."`, became `/v1/optimizer/proposals/*` -- which matched
    `/v1/optimizer/{dag_id}/proposals` and `/v1/optimizer/{dag_id}/run`,
    neither of them the route being called, and did **not** match the real
    `/v1/optimizer/proposals`. Deleting that route would have left this gate
    green: a false negative in precisely the class it exists for.
    """
    out: list[str] = []
    rest = raw
    while INTERPOLATION_START in rest:
        start = rest.index(INTERPOLATION_START)
        before = rest[:start]
        # Left to right, always from the FIRST `${`. Searching for a
        # well-formed one instead would skip past an earlier unparseable
        # interpolation and truncate in the wrong place -- in
        # `/v1/audit${qs ? `?${qs}` the *second* one parses cleanly, and
        # stopping there left a segment reading ``audit${qs ? `?``.
        match = INTERPOLATION_RE.match(rest, start)
        if match is None:
            out.extend(_segments(before))
            return out, True
        after = rest[match.end() :]
        if not (before.endswith("/") and (after == "" or after.startswith("/"))):
            # Glued to the segment before it: a suffix, not an id.
            out.extend(_segments(before))
            return out, True
        out.extend(_segments(before))
        out.append(WILDCARD)
        rest = after
    out.extend(_segments(rest))
    return out, False


def matches(call: Call, route_path: str, methods: frozenset[str] | None = None) -> bool:
    """Whether one frontend call can be served by one registered route.

    `methods` is the route's allowed verbs. A path match alone would accept
    `GET` against a POST-only route, where Starlette answers 405 and the
    control is as broken as if nothing were registered.

    A prefix claim does not check the verb: the route it will actually reach is
    not known, so the verb of a route it merely shares a prefix with says
    nothing.
    """
    want, prefix_only = parse(call.path)
    have = _segments(route_path)
    if not prefix_only and methods and call.method is not None and call.method not in methods:
        return False
    if prefix_only:
        if len(want) > len(have):
            return False
        have = have[: len(want)]
    elif len(want) != len(have):
        return False
    for c, r in zip(want, have, strict=True):
        if c == WILDCARD or (r.startswith("{") and r.endswith("}")):
            continue
        if c != r:
            return False
    return True


def method_of(lines: list[str], index: int) -> str | None:
    """The verb a call site uses, or None when it cannot be read.

    Read from the line and the two after it, because `fetch(url, {` routinely
    puts `method:` on the next line. An explicit `method:` wins over a helper
    name: `apiPost` is not used with an overriding option today, but if it ever
    is, the option is what the browser sends.

    A bare `fetch` with no options is a GET -- that is the fetch default, not a
    guess. Anything else unreadable stays None, and None checks no verb.
    """
    window = "\n".join(lines[index : index + 3])
    explicit = METHOD_RE.search(window)
    if explicit:
        return explicit.group("verb").upper()
    helper = HELPER_RE.search(lines[index])
    if helper:
        return HELPER_VERBS[helper.group("helper")]
    if "fetch(" in lines[index]:
        return "GET"
    return None


def _is_waived(lines: list[str], index: int) -> bool:
    candidates = [lines[index]]
    if index > 0:
        candidates.append(lines[index - 1])
    return any(WAIVER.search(c) or WAIVER_TS.search(c) for c in candidates)


def frontend_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.ts", "*.tsx", "*.js", "*.jsx"):
        for path in FRONTEND.rglob(pattern):
            if _SKIP_PARTS.intersection(path.parts):
                continue
            files.append(path)
    return sorted(files)


def calls_in(path: Path, repo_root: Path = REPO_ROOT) -> list[Call]:
    """Every `/v1/...` path this file requests, with its line.

    A base binding is resolved into the calls composed from it and is not
    itself reported, because it is not a request.

    `repo_root` only shortens the reported path. A parameter rather than the
    module global so a caller can read a file outside this repository -- which
    the tests do, and which a global would make them mutate.
    """
    rel = str(path.relative_to(repo_root))
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    bases = {m.group("name"): m.group("path") for m in BASE_RE.finditer(text)}
    binding_lines = {i for i, line in enumerate(lines) if BASE_RE.search(line)}

    out: list[Call] = []
    for index, line in enumerate(lines):
        if _is_waived(lines, index):
            continue
        verb = method_of(lines, index)

        def _add(raw: str, index: int = index, verb: str | None = verb) -> None:
            _, prefix_only = parse(raw)
            out.append(Call(rel, index + 1, raw, method=verb, prefix_only=prefix_only))

        for match in COMPOSED_RE.finditer(line):
            base = bases.get(match.group("name"))
            if base is not None:
                _add(base + match.group("rest"))
        # `fetch(API)` -- the base handed over whole rather than composed.
        for match in DIRECT_RE.finditer(line):
            base = bases.get(match.group("name"))
            if base is not None:
                _add(base)
        if index in binding_lines:
            continue
        for match in CALL_RE.finditer(line):
            _add(match.group("path"))
    return out


def import_paths() -> list[Path]:
    """What the app needs on `sys.path`, nearest-first.

    `packages/*/src` mirrors the root pyproject's `pythonpath`, so this gate
    behaves the same under pytest and as a bare CI step. Without it the
    optional routers fail to import here and the gate correctly refuses to
    answer -- a true statement about the wrong thing, which is how this was
    found.

    BACKEND is last in the list and therefore first on the path: the monorepo
    root also has a `services/` package that shadows the app's own when it wins
    the race, the same hazard `backend/tests/conftest.py` guards against.
    """
    return [*sorted(REPO_ROOT.glob("packages/*/src")), BACKEND]


def registered_routes() -> tuple[dict[str, frozenset[str]], list[str]]:
    """The app's route table as `{path: verbs}`, and any router that failed.

    Imported rather than parsed: this is the table Starlette matches against,
    so it is the only thing that answers "would this request find a handler".

    The verbs are kept because a path match alone accepts a GET against a
    POST-only route (#295 review). Two routes can share a path with different
    verbs, so the sets are unioned per path.
    """
    for entry in import_paths():
        if str(entry) in sys.path:
            sys.path.remove(str(entry))
        sys.path.insert(0, str(entry))
    os.environ.setdefault("HIVE_SKIP_DOTENV", "1")
    # Imported here, not at module scope: building the app is the expensive part
    # of this gate and there is no reason to pay it to print --help.
    from main import app

    degraded = [
        f"{module}: {cause}"
        for module, cause in getattr(app.state, "optional_routers", {}).items()
        if cause is not None
    ]
    table: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
        table.setdefault(path, set()).update(getattr(route, "methods", None) or ())
    return {p: frozenset(v) for p, v in sorted(table.items())}, degraded


def main() -> int:
    routes, degraded = registered_routes()
    if degraded:
        print("FAIL: the route table is incomplete, so no path can be judged against it\n")
        for entry in degraded:
            print(f"  optional router did not load -- {entry}")
        print(
            "\nEvery call into that router would be reported as unregistered, and the\n"
            "real cause is one layer down. Fix the import, then re-run."
        )
        return 1
    if not routes:
        print("FAIL: the app registered no routes at all; nothing was measured")
        return 1

    files = frontend_files()
    if not files:
        print(f"FAIL: no frontend sources found under {FRONTEND}")
        return 1

    calls = [call for path in files for call in calls_in(path, REPO_ROOT)]
    if not calls:
        print("FAIL: no /v1/ call sites found in the frontend; nothing was measured")
        return 1

    findings = [
        Finding(call)
        for call in calls
        if not any(matches(call, path, verbs) for path, verbs in routes.items())
    ]
    if findings:
        seen: set[tuple[str, int, str]] = set()
        unique = [
            f
            for f in findings
            if (f.call.source, f.call.line_no, f.call.path) not in seen
            and not seen.add((f.call.source, f.call.line_no, f.call.path))
        ]
        print(f"FAIL: {len(unique)} frontend call(s) reach no registered backend route\n")
        for finding in unique:
            print(finding.render())
            print()
        print(
            "`fetch` does not reject on a 404, so a control wired to a route nobody\n"
            "registered looks like it works and reports a state that never happened.\n"
            "See #295. Register the route, remove the caller, or waive with:\n"
            "  // frontend-api-routes: allow <reason>"
        )
        return 1

    print(
        f"ok: {len(calls)} frontend call site(s) across {len(files)} file(s) "
        f"resolve to {len(routes)} registered route(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
