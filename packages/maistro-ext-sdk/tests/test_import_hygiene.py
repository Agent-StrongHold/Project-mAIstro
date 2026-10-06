"""Import hygiene — acceptance criterion 4 of #949.

"SDK package does not import product-private runtime modules"

Enforced by AST over every module in the shipped package: the only legal
import roots are the standard library, pydantic, and the SDK itself. Any
``maistro`` product import — the private runtime the epic forbids — fails
with the offending module named. Static on purpose: an import inside an
``if`` or a function body is still a dependency, and running the package to
watch for ImportError would only prove the happy path.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Roots an SDK module may import: itself, pydantic (the one declared
#: dependency), and — behind the [yaml] extra — the YAML parser. Everything
#: else, ``maistro`` included, is product-private or undeclared, and fails.
_ALLOWED_ROOTS = frozenset({"maistro_ext_sdk", "pydantic", "yaml", "_yaml"})


def _sdk_modules() -> list[Path]:
    import maistro_ext_sdk

    return sorted(Path(maistro_ext_sdk.__file__).resolve().parent.glob("*.py"))


def _import_roots(tree: ast.AST) -> list[str]:
    """Every module referenced by import statements, including nested ones."""
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                roots.append(".")  # relative import: inside the SDK by definition
            elif node.module:
                roots.append(node.module)
    return roots


def test_every_sdk_module_imports_only_allowed_roots() -> None:
    offenders: list[str] = []
    for path in _sdk_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for root in _import_roots(tree):
            top = root.split(".")[0]
            if top in _ALLOWED_ROOTS or top in sys.stdlib_module_names:
                continue
            offenders.append(f"{path.name}: imports {root!r}")
    assert not offenders, (
        "SDK modules import outside the allowed roots "
        f"(stdlib, pydantic, maistro_ext_sdk): {offenders}"
    )


def test_product_private_packages_are_named_and_forbidden() -> None:
    """Fails loudly if someone widens the vocabulary: these are the
    product-private roots the epic forbids, and each must stay classified as
    an offender rather than silently fall out of the scan."""
    for private in ("maistro", "maistro_server", "maistro_turing"):
        assert private not in _ALLOWED_ROOTS
        assert private not in sys.stdlib_module_names


def test_declared_runtime_dependencies_match_the_scan() -> None:
    """pyproject declares what the scan allows: one runtime dependency
    (pydantic), so an undeclared import cannot pass the scan while missing
    from the wheel."""
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    names = {
        dep.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip()
        for dep in data["project"]["dependencies"]
    }
    assert names == {"pydantic"}, f"unexpected runtime dependencies: {names}"
