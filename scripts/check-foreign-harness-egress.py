#!/usr/bin/env python3
"""Gate: no product caller talks to OpenClaw/Pi HTTP/CLI outside the Provider
boundary (issue #1613, M1-D).

A foreign harness is admitted as one governed graph node: Provider -> Binding
-> Invocation. The transport to OpenClaw (gateway CLI/HTTP) and Pi (coding-agent
print-mode turn) belongs inside the provider implementations under
``maistro.capabilities.providers`` (and their immediate graph-side adapters).
A product module that references a foreign harness *and* performs its own
transport call is a raw side door: same harness, but no Binding, no Invocation
row, no Warden/ActionGate, no parent Run identity.

This gate fails when a module under the governed product trees

1. references a governed foreign harness by name (``openclaw`` family, or the
   Pi provider/CLI markers), and
2. performs a transport-shaped call — an HTTP client method or a
   subprocess/spawn call — with the harness reference in the same module,

unless the module is inside the declared Provider boundary (or is a test or
this gate itself).

What this detector honestly does not catch
------------------------------------------
A caller that talks to OpenClaw/Pi without naming either harness — e.g. a bare
``httpx.post(gateway_url, ...)`` where ``gateway_url`` arrives from config —
is outside a static detector's reach. That gap is what the Invocation ledger
and reconciliation are for: an egress with no Invocation row under it is
auditable as an orphan. Naming the harness in code is the cheap thing to
refuse; this gate refuses it.

Usage
-----
    python3 scripts/check-foreign-harness-egress.py
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Trees this gate governs: shipped library and product code.
GOVERNED: tuple[str, ...] = (
    "packages/maistro-core/src",
    "packages/maistro-canvas/src",
    "packages/maistro-turing/src",
    "packages/maistro-rsi/src",
    "packages/maistro-bootstrap/src",
    "packages/maistro-registry/src",
    "packages/hive-conductor/backend",
)

#: The one place harness transport is allowed to live: the provider
#: implementations and their immediate graph/session adapters.
BOUNDARY: tuple[str, ...] = (
    "packages/maistro-core/src/maistro/capabilities/providers/",
    "packages/maistro-core/src/maistro/capabilities/slots/harness_runner.py",
    "packages/maistro-core/src/maistro/capabilities/slots/harness.py",
    "packages/maistro-core/src/maistro/capabilities/harness_manager.py",
    "packages/maistro-core/src/maistro/graph/harness.py",
    "packages/maistro-core/src/maistro/graph/harness_executor.py",
    # ADR-101 §2 hierarchical orchestration: this module is the *peer* client
    # for maistro's own HarnessRunner adapter-server protocol (it POSTs an
    # ExportBundle to another orchestrator's /v1/harness/sessions, the same
    # protocol hive-conductor serves). It cannot reach OpenClaw's gateway or
    # Pi's CLI — those speak their own product APIs and stay provider-only.
    "packages/maistro-core/src/maistro/orchestrator/hierarchy.py",
)

#: Substrings (lowercased) that name a governed foreign harness. Anything not
#: on this list is not a governed harness, so talking to it is not this gate's
#: question.
HARNESS_MARKERS: tuple[str, ...] = (
    "openclaw",
    "open-claw",
    "clawdbot",  # OpenClaw's former name
    "moltbot",  # OpenClaw's former name
    "piharnessrunner",  # the Pi provider class
    "providers.pi",  # the Pi provider module path
    "pi-mono",  # the Pi coding-agent project
    "--print-mode",  # Pi's non-interactive turn flag
    "pi -p",  # Pi's print-mode invocation shape
)

#: Modules whose (direct or aliased) use counts as a transport call, mapped
#: to the calls that actually perform egress on each. HTTP clients cover the
#: gateway path; subprocess/OS process spawns cover CLI harnesses (Pi print
#: mode, ``openclaw agent ...``). The call sets are per-module and precise so
#: ``asyncio.run``, ``os.getenv``, or ``dict.get`` never false-positive.
TRANSPORT_CALLS: dict[str, frozenset[str]] = {
    "httpx": frozenset(
        {"request", "post", "put", "patch", "delete", "stream", "send", "Client", "AsyncClient"}
    ),
    "requests": frozenset({"request", "post", "put", "patch", "delete", "Session"}),
    "aiohttp": frozenset({"request", "post", "put", "patch", "delete", "ClientSession"}),
    "urllib": frozenset({"urlopen", "request"}),
    "urllib3": frozenset({"request", "PoolManager"}),
    "http": frozenset({"HTTPConnection", "HTTPSConnection", "request"}),
    "websockets": frozenset({"connect", "serve"}),
    "subprocess": frozenset({"run", "call", "check_call", "check_output", "Popen"}),
    "os": frozenset({"system", "popen", "exec", "execv", "execve", "execvp", "spawnl", "spawnv"}),
    "asyncio": frozenset({"create_subprocess_exec", "create_subprocess_shell"}),
}

_TRANSPORT_ROOTS = frozenset(TRANSPORT_CALLS)

#: HTTP verbs unambiguous enough to flag on any receiver: no stdlib/container
#: type grows a ``.post()``. ``get``/``send``/``run`` are NOT here — they are
#: flagged only via a transport-module binding.
HTTP_VERBS: frozenset[str] = frozenset({"post", "put", "patch", "delete"})


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    call: str
    marker: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: product module performs transport "
            f"call {self.call!r} while referencing foreign harness marker "
            f"{self.marker!r} outside the Provider boundary"
        )


def _governed_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for tree in GOVERNED:
        base = root / tree
        if not base.exists():  # pragma: no cover - package layout guard
            continue
        files.extend(p for p in base.rglob("*.py") if p.is_file())
    return sorted(files)


def _in_boundary(relative: str) -> bool:
    return any(relative == b or relative.startswith(b) for b in BOUNDARY)


def _is_test_or_gate(relative: str) -> bool:
    parts = relative.split("/")
    return "test" in parts or "tests" in parts or relative.startswith("scripts/")


def _transport_bindings(tree: ast.AST) -> dict[str, set[str]]:
    """Map bound names to the transport modules they may stand for.

    ``import httpx`` binds ``httpx``; ``import subprocess as sp`` binds ``sp``;
    ``from subprocess import Popen`` binds ``Popen`` (a direct call target).
    """
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if TRANSPORT_CALLS.get(alias.name) is None and TRANSPORT_CALLS.get(root) is None:
                    continue
                bindings[alias.asname or root] = {root}
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            root = node.module.split(".")[0]
            if TRANSPORT_CALLS.get(node.module) is None and TRANSPORT_CALLS.get(root) is None:
                continue
            for alias in node.names:
                bindings.setdefault(alias.asname or alias.name, set()).add(root)
    return bindings


def _root_name(node: ast.AST) -> str | None:
    """Dotted root identifier of a call target, if it is name-rooted."""
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        parts.reverse()
        return parts[0]
    return None


def transport_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """Line/call pairs where transport egress appears.

    Two shapes are flagged:

    - a call on a transport-module binding (``subprocess.run``, ``sp.Popen``),
    - an unambiguous HTTP verb on any receiver (``await client.post(...)`` —
      the client may be a local variable, not the module binding itself).

    Ambiguous names (``get``, ``send``, ``run``, ``request``) are only flagged
    when the receiver is a transport-module binding, so ``dict.get`` and
    ``asyncio.run`` stay clean.
    """
    bindings = _transport_bindings(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in HTTP_VERBS:
                found.append((node.lineno, f".{node.func.attr}()"))
                continue
            root = _root_name(node.func.value)
            modules = bindings.get(root or "", set())
            for module in modules:
                if node.func.attr in TRANSPORT_CALLS[module]:
                    found.append((node.lineno, f"{root}.{node.func.attr}"))
                    break
        elif isinstance(node.func, ast.Name):
            # direct call of an imported egress function, e.g. urlopen(...)
            modules = bindings.get(node.func.id, set())
            for module in modules:
                if node.func.id in TRANSPORT_CALLS[module]:
                    found.append((node.lineno, node.func.id))
                    break
    return found


def harness_markers(source: str) -> list[str]:
    lowered = source.lower()
    return [m for m in HARNESS_MARKERS if m in lowered]


def scan_file(path: Path, root: Path) -> list[Violation]:
    relative = path.relative_to(root).as_posix()
    if _in_boundary(relative) or _is_test_or_gate(relative):
        return []
    source = path.read_text(encoding="utf-8")
    markers = harness_markers(source)
    if not markers:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [Violation(path, 1, "<unparsable module>", markers[0])]
    return [
        Violation(path, line, call, marker)
        for line, call in transport_calls(tree)
        for marker in markers[:1]
    ]


def scan(root: Path = ROOT) -> list[Violation]:
    violations: list[Violation] = []
    for path in _governed_files(root):
        violations.extend(scan_file(path, root))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="Repository root (defaults to this checkout; tests inject a fixture tree)",
    )
    args = parser.parse_args(argv)
    violations = scan(Path(args.root))
    for violation in violations:
        print(violation.render(), file=sys.stderr)
    if violations:
        print(
            f"check-foreign-harness-egress: {len(violations)} violation(s); "
            "foreign-harness transport belongs inside maistro.capabilities.providers "
            "(Provider -> Binding -> Invocation), not in product callers (#1613).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
