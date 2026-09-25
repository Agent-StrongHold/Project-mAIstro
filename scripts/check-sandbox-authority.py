#!/usr/bin/env python3
"""Gate: product code-execution consumers use the one sandbox authority (#18).

ADR-093 decision 4 and SPEC-190 give `maistro.sandbox` one job: be the only
sandbox policy authority — protocol, policy ladder, selector, egress grants —
with backends registering *behind* it. #18 closed because production still
constructed sandboxes outside that machinery: `hyperlight_executor` carried a
second tier table, second detection and five private launchers, and its
bubblewrap argv existed twice.

What this gate enforces, mechanically, on every non-test Python file under
``packages/``:

1. **No direct backend construction** — `BubblewrapSandboxBackend`,
   `ContainerSandboxBackend` and `FakeSandboxBackend` are constructed only by
   `maistro.sandbox.wiring` (and tests, which are exempt: pinning a backend is
   not wielding one). Anyone else instantiating one is standing up a private
   selection path that the selector's fail-closed ladder never saw.
2. **No backend imports outside the authority** — importing
   `maistro.sandbox.backends.*` from product code is the import-shaped version
   of rule 1 and usually a prelude to it.
3. **No hand-built sandbox launchers** — the bwrap/gVisor/Firecracker flag
   vocabulary (`--unshare-all`, `--share-net`, `--die-with-parent`,
   `--clearenv`, `--new-session`, `--runtime=runsc`, `firecracker-containerd`)
   *and* the container-run vocabulary (`--cap-add`, `--cap-drop`,
   `--security-opt`, `--tmpfs`, `--pids-limit`, `--read-only`,
   `--network=none`, `--network=host`, `--privileged`, `--userns`) may appear
   only inside `maistro.sandbox`. Those flags *are* the security content of a
   Tier-2/3 backend; a second place that assembles them is a second backend,
   unreviewed by the conformance suite (#80).
4. **No speculative microVM imports** — `import hyperlight` / `import
   firecracker` nowhere in product code: no Tier-1/2 backend ships, and the
   retired executor's `_has_hyperlight()` import probe is exactly how a false
   capability claim got built. When a real VM backend lands behind the
   protocol it will live in `maistro.sandbox.backends`, and this rule is the
   one to relax.
5. **The documented seams stay behind the authority.** Product modules that
   carry launcher vocabulary by documented decision are pinned individually:

   - `services/hyperlight_executor.py` must import from `maistro.sandbox`.
     The module is retained only as the dict-shaped compatibility seam that
     `legacy_dag_node` and the injection tests consume; if it ever stops
     naming the canonical authority it has silently become a second one
     again.
   - `tools/sandbox/docker.py` must import from `maistro.sandbox`: it was
     retired from being a second launcher and rewritten as the legacy
     call-signature facade over the selector/policy authority (#18).
   - `builders/container_sandbox.py` (maistro-bootstrap) is a data-plane
     sandbox: its bulk repo seed/sync travels as tar over stdin/stdout
     pipes, which cannot fit the bounded `SandboxProtocol.exec` capture
     (#1197), and maistro-bootstrap deliberately does not depend on
     maistro-core. It is registered in AUTHORIZED_SEAM_POSTURE instead: the
     gate fails if its default-deny egress, cap-drop, no-new-privileges or
     non-root-uid posture ever regresses. Its full convergence onto the
     selector authority is recorded in
     `docs/testing/inventory-notes/18-sandbox-authority.md`.

Usage::

    python3 scripts/check-sandbox-authority.py
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The one sandbox authority. Everything below is allowed to do anything
#: sandbox-shaped inside this directory; nobody else is.
AUTHORITY = REPO_ROOT / "packages" / "maistro-core" / "src" / "maistro" / "sandbox"

#: The legacy compatibility seam. It must keep consuming the authority.
ADAPTER = (
    REPO_ROOT / "packages" / "hive-conductor" / "backend" / "services" / "hyperlight_executor.py"
)

#: The retired second launcher, now the legacy call-signature facade over the
#: selector/policy authority. The gate pins that it keeps naming the authority.
FACADE = (
    REPO_ROOT / "packages" / "maistro-core" / "src" / "maistro" / "tools" / "sandbox" / "docker.py"
)

#: The builders data-plane sandbox (see rule 5): authorized to carry launcher
#: vocabulary because its bulk seed/sync cannot fit the bounded protocol exec,
#: but its documented #77/#78 posture is pinned here and must not regress.
BOOTSTRAP_BUILDER = (
    REPO_ROOT
    / "packages"
    / "maistro-bootstrap"
    / "src"
    / "maistro_bootstrap"
    / "builders"
    / "container_sandbox.py"
)

#: Posture every authorized-seam file must keep, as (needle, what it pins).
AUTHORIZED_SEAM_POSTURE: dict[Path, tuple[tuple[str, str], ...]] = {
    BOOTSTRAP_BUILDER: (
        ("--network=none", "default-deny egress (#77)"),
        ("--cap-drop=ALL", "no capability survives the drop"),
        ("--security-opt=no-new-privileges", "no setuid escape inside the sandbox"),
        ("65532:65532", "candidate code never runs as container root (#77)"),
    ),
}

BACKEND_CLASSES = frozenset(
    {
        "BubblewrapSandboxBackend",
        "ContainerSandboxBackend",
        "FakeSandboxBackend",
    }
)

LAUNCHER_FLAGS = (
    "--unshare-all",
    "--share-net",
    "--die-with-parent",
    "--clearenv",
    "--new-session",
    "--runtime=runsc",
    "firecracker-containerd",
    # Container-run vocabulary: the security content of a Tier-3 launcher.
    "--cap-add",
    "--cap-drop",
    "--security-opt",
    "--tmpfs",
    "--pids-limit",
    "--read-only",
    "--network=none",
    "--network=host",
    "--privileged",
    "--userns",
)

MICROVM_MODULES = frozenset({"hyperlight", "firecracker"})


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    rule: str
    detail: str

    def render(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT)}:{self.line}: {self.rule}: {self.detail}"


def _is_test(path: Path) -> bool:
    return "/tests/" in path.as_posix() or path.name.startswith("test_")


def _product_python(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        posix = path.as_posix()
        if (
            "/.venv/" in posix
            or "__pycache__" in posix
            or "/mutants/" in posix
            or "/benchmarks/third_party/" in posix
            or "/node_modules/" in posix
            or _is_test(path)
        ):
            continue
        yield path


def _iter_strings(node: ast.AST) -> Iterator[tuple[int, str]]:
    """Every string constant in the tree, at the position it appears."""
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.lineno, child.value


def _iter_names(node: ast.AST) -> Iterator[tuple[int, str]]:
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            yield child.lineno, child.id
        elif isinstance(child, ast.Attribute):
            yield child.lineno, child.attr


def _iter_import_modules(node: ast.AST) -> Iterator[tuple[int, str]]:
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                yield child.lineno, alias.name
        elif isinstance(child, ast.ImportFrom):
            module = child.module or ""
            names = [alias.name for alias in child.names]
            yield child.lineno, module
            # `from maistro.sandbox import backends` makes `backends` a name
            # that attribute chains then extend; record the dotted forms.
            for name in names:
                yield child.lineno, f"{module}.{name}" if module else name


def _check_imports(path: Path, tree: ast.AST) -> Iterator[Violation]:
    for lineno, module in _iter_import_modules(tree):
        if module.startswith("maistro.sandbox.backends"):
            yield Violation(
                path,
                lineno,
                "backend-import-outside-authority",
                f"import of {module!r}: backends are reached through "
                "maistro.sandbox.wiring/selector, not imported directly",
            )
        root_module = module.split(".")[0]
        if root_module in MICROVM_MODULES:
            yield Violation(
                path,
                lineno,
                "microvm-import",
                f"import of {module!r}: no Tier-1/2 backend ships; a VM "
                "boundary arrives only as a backend behind maistro.sandbox "
                "(relax this rule when one does)",
            )


def _check_constructs_and_flags(
    path: Path, tree: ast.AST, *, launcher_vocabulary: bool = True
) -> Iterator[Violation]:
    for lineno, name in _iter_names(tree):
        if name in BACKEND_CLASSES:
            yield Violation(
                path,
                lineno,
                "direct-backend-construction",
                f"{name!r} may only be constructed by maistro.sandbox.wiring",
            )
    if not launcher_vocabulary:
        # A registered authorized seam may carry launcher flags (rule 5); its
        # containment posture is pinned by check_authorized_seam_posture.
        return
    for lineno, literal in _iter_strings(tree):
        for flag in LAUNCHER_FLAGS:
            if flag in literal:
                yield Violation(
                    path,
                    lineno,
                    "hand-built-sandbox-launcher",
                    f"launcher flag {flag!r} assembled outside maistro.sandbox; "
                    "the flags are the boundary, and a second assembler is a "
                    "second backend the conformance suite never reviewed",
                )


def check_file(path: Path, tree: ast.AST) -> Iterator[Violation]:
    in_authority = AUTHORITY in path.parents or path == AUTHORITY
    if in_authority:
        return
    yield from _check_imports(path, tree)
    yield from _check_constructs_and_flags(
        path, tree, launcher_vocabulary=path not in AUTHORIZED_SEAM_POSTURE
    )


def check_facade() -> Iterator[Violation]:
    if not FACADE.is_file():
        yield Violation(
            FACADE,
            0,
            "facade-missing",
            "tools/sandbox/docker.py is gone: update this gate — the module is "
            "the legacy call-signature seam for the evolve benchmark and RSI's "
            "development sandbox",
        )
        return
    tree = ast.parse(FACADE.read_text(encoding="utf-8"))
    modules = [module for _, module in _iter_import_modules(tree)]
    if not any(
        module == "maistro.sandbox" or module.startswith("maistro.sandbox.") for module in modules
    ):
        yield Violation(
            FACADE,
            1,
            "facade-not-behind-authority",
            "the legacy docker-sandbox seam no longer imports maistro.sandbox; "
            "it has become a second sandbox authority again",
        )


def check_authorized_seam_posture() -> Iterator[Violation]:
    for seam, needles in AUTHORIZED_SEAM_POSTURE.items():
        if not seam.is_file():
            yield Violation(
                seam,
                0,
                "authorized-seam-missing",
                "a registered authorized seam disappeared: update "
                "AUTHORIZED_SEAM_POSTURE deliberately, not incidentally",
            )
            continue
        source = seam.read_text(encoding="utf-8")
        for needle, what in needles:
            if needle not in source:
                yield Violation(
                    seam,
                    0,
                    "authorized-seam-posture-regressed",
                    f"{what} is no longer pinned in this authorized seam "
                    f"({needle!r} not found): it has silently weakened below "
                    "its documented containment",
                )


def check_adapter() -> Iterator[Violation]:
    if not ADAPTER.is_file():
        yield Violation(
            ADAPTER,
            0,
            "adapter-missing",
            "services/hyperlight_executor.py is gone: update this gate — the "
            "module is the compatibility seam for legacy_dag_node and its "
            "injection tests",
        )
        return
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    modules = [module for _, module in _iter_import_modules(tree)]
    if not any(
        module == "maistro.sandbox" or module.startswith("maistro.sandbox.") for module in modules
    ):
        yield Violation(
            ADAPTER,
            1,
            "adapter-not-behind-authority",
            "the legacy executor adapter no longer imports maistro.sandbox; "
            "it has become a second sandbox authority again",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true", help="print the scanned file count")
    args = parser.parse_args(argv)

    violations: list[Violation] = []
    scanned = 0
    for path in _product_python(REPO_ROOT / "packages"):
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            violations.append(Violation(path, exc.lineno or 0, "parse-error", str(exc)))
            continue
        violations.extend(check_file(path, tree))
    violations.extend(check_adapter())
    violations.extend(check_facade())
    violations.extend(check_authorized_seam_posture())

    if args.verbose:
        print(f"checked {scanned} product files under packages/")
    if violations:
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        print(f"sandbox-authority: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("sandbox-authority: ok — one sandbox authority, no private launchers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
