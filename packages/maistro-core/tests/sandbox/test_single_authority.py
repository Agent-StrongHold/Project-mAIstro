"""One sandbox authority: no product consumer constructs a direct sandbox (#76).

The issue's final acceptance criterion names this test shape: if a supported
code-execution consumer again constructs a direct sandbox implementation
outside the canonical selector, a reachability/convergence check must fail.
The reachability ratchet already refuses a *product import* of the retired
Docker sandbox (`maistro.tools.sandbox.docker` was removed outright by the
#76 cutover, so any import now fails at collection); this module covers what
an import graph cannot see — constructing a sandbox class or a container CLI
argv at runtime from product code.

Scanned: production source trees under ``packages/*/src`` only. Tests, tooling
and the first-party stack deployment path (``maistro.cli._container`` —
running the engine's own containers, ADR-093 decision 3, not code execution)
are out of scope by design.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[4]

#: Concrete constructors, including aliases and module-qualified calls.
_DIRECT_CONSTRUCTIONS = {
    "MicroVMSandbox",
    "SandboxContainer",
    "CanonicalSandboxContainer",
    "KataSandboxBackend",
    "LauncherVMSandboxBackend",
    "BubblewrapSandboxBackend",
    "FakeSandboxBackend",
}

#: Import statements that reach around the selector to the retired backend.
_LEGACY_IMPORT_RE = re.compile(
    r"^\s*from\s+maistro\.tools\.sandbox\.docker\s+import\b"
    r"|^\s*from\s+maistro\.tools\.sandbox\s+import\s+docker\b"
    r"|^\s*import\s+maistro\.tools\.sandbox\.docker\b",
    re.MULTILINE,
)

#: A `docker ... run` argv built outside the sandbox backends: the canonical
#: backends use the CLI as their OCI transport (Kata) — nobody else may.
_DOCKER_RUN_RE = re.compile(r"[\"']docker[\"']\s*,\s*[\"']run[\"']")

#: Paths allowed to do the things above: the backend implementations
#: themselves, and the canonical adapters that enter through the selector.
_ALLOWED_PREFIXES = (
    "packages/maistro-core/src/maistro/sandbox/backends/",
    "packages/maistro-core/src/maistro/sandbox/wiring.py",
    "packages/maistro-core/src/maistro/tools/sandbox/",
)


def _production_files() -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for src in sorted(_ROOT.glob("packages/*/src")):
        for path in sorted(src.rglob("*.py")):
            rel = path.relative_to(_ROOT).as_posix()
            files.append((rel, path.read_text(encoding="utf-8", errors="replace")))
    return files


def _offenders(predicate) -> list[str]:
    return [
        rel
        for rel, text in _production_files()
        if not rel.startswith(_ALLOWED_PREFIXES) and predicate(text)
    ]


def _constructs_implementation(text: str) -> bool:
    tree = ast.parse(text)
    aliases = {
        alias.asname or alias.name: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = aliases.get(node.func.id, node.func.id)
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        if name in _DIRECT_CONSTRUCTIONS:
            return True
    return False


@pytest.mark.parametrize("name", sorted(_DIRECT_CONSTRUCTIONS))
@pytest.mark.parametrize("form", ["direct", "aliased", "qualified"])
def test_convergence_rejects_in_memory_product_bypass(monkeypatch, name, form):
    if form == "aliased":
        text = f"from maistro.sandbox.backends.kata import {name} as Backend\nBackend()"
    elif form == "qualified":
        text = f"import maistro.sandbox.backends.kata as backend\nbackend.{name}()"
    else:
        text = f"{name}()"
    production = _production_files()
    monkeypatch.setattr(
        __import__(__name__, fromlist=["_production_files"]),
        "_production_files",
        lambda: [*production, ("packages/product/src/bypass.py", text)],
    )
    with pytest.raises(AssertionError, match=r"bypass\.py"):
        test_no_product_code_constructs_a_sandbox_implementation_directly()


def test_no_product_code_constructs_a_sandbox_implementation_directly() -> None:
    """`MicroVMSandbox`/`SandboxContainer` may be constructed only inside the
    sandbox package (backends and the canonical adapter). A consumer that
    wants execution builds a selector and asks it (#76)."""
    offenders = _offenders(_constructs_implementation)
    assert offenders == [], (
        "product code constructed a sandbox implementation outside the canonical "
        f"selector authority: {sorted(set(offenders))}"
    )


def test_no_product_code_imports_the_retired_docker_sandbox() -> None:
    offenders = _offenders(lambda text: bool(_LEGACY_IMPORT_RE.search(text)))
    assert offenders == [], (
        "product code imports maistro.tools.sandbox.docker instead of the "
        f"canonical selector: {offenders}"
    )


def test_no_product_code_builds_a_docker_run_argv_outside_the_backends() -> None:
    offenders = _offenders(lambda text: bool(_DOCKER_RUN_RE.search(text)))
    assert offenders == [], (
        "product code launches containers through the Docker CLI directly "
        f"instead of the canonical selector: {offenders}"
    )
