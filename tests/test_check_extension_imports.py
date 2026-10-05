"""Tests for the extension import-boundary gate (#951, M9-A3).

The gate (`scripts/check-extension-imports.py`) enforces the namespace policy
in `extensions/namespace-policy.json`: extension packages may import the
public extension SDK root, the standard library, their own package, and the
dependencies they declare — nothing else first-party, nothing repo-relative,
no `sys.path` repair.

Everything here runs against fabricated extension trees in a tmp directory
(the same pattern `test_dependency_namespaces.py` uses), plus two tests
against the real tree: the gate must pass the shipped reference extension,
and — the acceptance criterion the issue names — conformance must FAIL when
that same reference extension imports a product-private module.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = ROOT / "scripts" / "check-extension-imports.py"
REAL_POLICY = ROOT / "extensions" / "namespace-policy.json"
REFERENCE_EXTENSION = ROOT / "extensions" / "reference-greeter"


@pytest.fixture(scope="module")
def gate() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_extension_imports", CHECK_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_extension_imports"] = module
    spec.loader.exec_module(module)
    return module


def write_policy(directory: Path, **overrides: object) -> Path:
    """A policy with the real one's shape, pointed at fabricated trees."""
    policy = {
        "policy_version": "1.0.0",
        "public_sdk_namespaces": ["maistro_ext_sdk"],
        "product_private_namespaces": ["maistro", "maistro_server", "maistro_canvas"],
        "extension_trees": ["ext/*"],
        "test_only_namespaces": ["pytest"],
    }
    policy.update(overrides)
    path = directory / "namespace-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def make_extension(
    directory: Path,
    name: str = "my-ext",
    dependencies: list[str] | None = None,
    files: dict[str, str] | None = None,
    tests: dict[str, str] | None = None,
) -> Path:
    """A minimal buildable-looking extension with the given source files."""
    ext = directory / "ext" / name
    (ext / "src" / name.replace("-", "_")).mkdir(parents=True)
    (ext / "tests").mkdir()
    deps = "\n".join(f'    "{d}",' for d in (dependencies or []))
    (ext / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "1.0.0"\ndependencies = [\n' + deps + "\n]\n",
        encoding="utf-8",
    )
    for filename, body in (files or {"__init__.py": ""}).items():
        target = ext / "src" / name.replace("-", "_") / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    for filename, body in (tests or {}).items():
        (ext / "tests" / filename).write_text(body, encoding="utf-8")
    return ext


def scan(gate: types.ModuleType, ext: Path, policy_path: Path) -> list[str]:
    """All violations (both passes) for one extension, as strings."""
    policy = gate.load_policy(policy_path)
    violations = gate.scan_extension(ext, policy) + gate.scan_private_modules(
        ext, policy.public_sdk_namespaces
    )
    return [str(v) for v in violations]


# ---------------------------------------------------------------------------
# the real tree
# ---------------------------------------------------------------------------


def test_gate_passes_the_shipped_reference_extension(gate: types.ModuleType) -> None:
    """The real policy, the real tree: green, and the extension is discovered."""
    assert gate.main([f"--policy={REAL_POLICY}"]) == 0
    policy = gate.load_policy(REAL_POLICY)
    assert [p.name for p in gate.discover_extensions(ROOT, policy)] == ["reference-greeter"]


def test_policy_classifies_every_first_party_import_root(gate: types.ModuleType) -> None:
    """The closed-classification direction: every shipped root is on a list."""
    policy = gate.load_policy(REAL_POLICY)
    shipped = gate.first_party_import_roots(ROOT)
    assert shipped, "no first-party import roots found; the glob stopped matching"
    classified = set(policy.public_sdk_namespaces) | set(policy.product_private_namespaces)
    assert shipped <= classified
    # The SDK root is the ONLY public first-party namespace, and the product
    # roots the epic names are on the private side.
    assert policy.public_sdk_namespaces == ("maistro_ext_sdk",)
    assert {"maistro", "maistro_server"} <= set(policy.product_private_namespaces)


# ---------------------------------------------------------------------------
# acceptance criterion 1: conformance fails on product-private imports
# ---------------------------------------------------------------------------


def test_conformance_fails_when_the_reference_extension_imports_private_modules(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    """A copy of the real reference extension plus one private import: red."""
    ext = tmp_path / "ext" / REFERENCE_EXTENSION.name
    shutil.copytree(REFERENCE_EXTENSION, ext)
    policy_path = write_policy(tmp_path)
    plugin = ext / "src" / "reference_greeter" / "plugin.py"

    clean = scan(gate, ext, policy_path)
    assert clean == [], "the pristine copy must pass before the mutation"

    plugin.write_text(
        plugin.read_text(encoding="utf-8")
        + "\nfrom maistro.security.warden import _regex  # the defect\n",
        encoding="utf-8",
    )
    violations = scan(gate, ext, policy_path)
    assert any("product-private import" in v and "maistro" in v for v in violations)
    # The defect line is quoted well enough to fix without re-running.
    assert any("_regex" in v for v in violations)


# ---------------------------------------------------------------------------
# each violation class, on fabricated trees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected_fragment"),
    [
        ("import maistro_server\n", "product-private import"),
        ("from maistro import agents\n", "product-private import"),
        ("from packages.maistro_core import agents\n", "repo-relative import"),
        ("import extensions.namespace_policy\n", "repo-relative import"),
        ("import httpx\n", "undeclared third-party import"),
        ("import sys\nsys.path.insert(0, 'packages')\n", "sys.path"),
        ("import sys\nsys.path.append('../src')\n", "sys.path"),
        (
            "import importlib\nimportlib.import_module('maistro')\n",
            "product-private import",
        ),
        ("value = __import__('maistro_server')\n", "product-private import"),
        ("from maistro_ext_sdk import _internal\n", "private import"),
        ("import maistro_ext_sdk._internal\n", "private import"),
        ("from maistro_ext_sdk._internal import thing\n", "private import"),
    ],
)
def test_violation_classes_are_named(
    gate: types.ModuleType, tmp_path: Path, body: str, expected_fragment: str
) -> None:
    ext = make_extension(tmp_path, files={"mod.py": body})
    violations = scan(gate, ext, write_policy(tmp_path))
    assert any(expected_fragment in v for v in violations), violations


def test_allowed_imports_pass(gate: types.ModuleType, tmp_path: Path) -> None:
    ext = make_extension(
        tmp_path,
        dependencies=["httpx>=0.28"],
        files={
            "__init__.py": "from maistro_ext_sdk import manifest\n",
            "mod.py": (
                "import json\nimport httpx\nfrom . import helper\nfrom .helper import thing\n"
            ),
            "helper.py": "thing = 1\n",
        },
        tests={"test_ok.py": "import pytest\n\ndef test_ok():\n    assert True\n"},
    )
    assert scan(gate, ext, write_policy(tmp_path)) == []


# ---------------------------------------------------------------------------
# the manifest entrypoint: a host imports it as extension code, so the
# boundary applies with no Python import statement for the .py scans to see
# ---------------------------------------------------------------------------


def write_manifest(ext: Path, entrypoint_module: str) -> None:
    """An extension.json whose entrypoint names the given module path."""
    (ext / "extension.json").write_text(
        json.dumps(
            {
                "id": "test.ext",
                "version": "1.0.0",
                "contract": ">=1.0.0",
                "family": "tool",
                "entrypoint": {"module": entrypoint_module, "object": "PLUGIN"},
            }
        ),
        encoding="utf-8",
    )


def test_entrypoint_in_the_own_namespace_passes(gate: types.ModuleType, tmp_path: Path) -> None:
    ext = make_extension(tmp_path, files={"plugin.py": ""})
    write_manifest(ext, "my_ext.plugin")
    assert scan(gate, ext, write_policy(tmp_path)) == []


@pytest.mark.parametrize(
    ("module", "expected_fragment"),
    [
        ("maistro.security.warden", "product-private entrypoint"),
        ("maistro_server", "product-private entrypoint"),
        ("packages.maistro_core.plugin", "repo-relative entrypoint"),
        ("extensions.evil", "repo-relative entrypoint"),
        ("maistro_ext_sdk.plugin", "outside the extension's own namespace"),
        ("httpx", "outside the extension's own namespace"),
    ],
)
def test_entrypoints_outside_the_own_namespace_fail(
    gate: types.ModuleType, tmp_path: Path, module: str, expected_fragment: str
) -> None:
    ext = make_extension(tmp_path)  # no .py import anywhere — the point of this check
    write_manifest(ext, module)
    violations = scan(gate, ext, write_policy(tmp_path))
    assert any(expected_fragment in v and module in v for v in violations), violations


def test_private_entrypoint_under_the_own_namespace_fails(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    ext = make_extension(tmp_path, files={"_impl.py": ""})
    write_manifest(ext, "my_ext._impl.plugin")
    assert any("private entrypoint" in v for v in scan(gate, ext, write_policy(tmp_path)))


def test_unreadable_manifest_fails(gate: types.ModuleType, tmp_path: Path) -> None:
    ext = make_extension(tmp_path)
    (ext / "extension.json").write_text("{ not json", encoding="utf-8")
    assert any(
        "unreadable extension manifest" in v for v in scan(gate, ext, write_policy(tmp_path))
    )


def test_reference_extension_entrypoint_names_its_own_namespace(
    gate: types.ModuleType,
) -> None:
    """The real manifest: entrypoint root == the wheel's packaged import root."""
    policy = gate.load_policy(REAL_POLICY)
    ext = gate.discover_extensions(ROOT, policy)[0]
    assert (
        gate.manifest_entrypoint_violations(
            ext, policy, gate.own_import_root(ext / "pyproject.toml")
        )
        == []
    )


def test_undeclared_dependency_fails_but_declaring_it_passes(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    files = {"mod.py": "import httpx\n"}
    undeclared = make_extension(tmp_path / "a", files=files)
    assert any("undeclared" in v for v in scan(gate, undeclared, write_policy(tmp_path / "a")))

    declared = make_extension(tmp_path / "b", dependencies=["httpx>=0.28,<1"], files=files)
    assert scan(gate, declared, write_policy(tmp_path / "b")) == []


def test_test_only_roots_are_allowed_only_under_tests(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    shipped = make_extension(tmp_path, files={"mod.py": "import pytest\n"})
    violations = scan(gate, shipped, write_policy(tmp_path))
    assert any("undeclared third-party import" in v for v in violations)

    tested = make_extension(tmp_path / "b", tests={"test_x.py": "import pytest\n"})
    assert scan(gate, tested, write_policy(tmp_path / "b")) == []


def test_tests_package_inside_the_shipped_namespace_is_not_test_only(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    """A manifest entrypoint may live at ``src/root/tests/plugin.py``.

    It is within the extension's own import root, so the entrypoint gate
    accepts it — which is exactly why the import gate must not mistake it
    for test code: a host imports it without pytest installed.
    """
    ext = make_extension(tmp_path, files={"tests/plugin.py": "import pytest\n"})
    violations = scan(gate, ext, write_policy(tmp_path))
    assert any("undeclared third-party import" in v for v in violations)


def test_imports_nested_in_functions_and_type_checking_are_still_caught(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    body = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import maistro_server\n"
        "def f():\n"
        "    import maistro\n"
        "    return maistro\n"
    )
    ext = make_extension(tmp_path, files={"mod.py": body})
    violations = scan(gate, ext, write_policy(tmp_path))
    assert sum("product-private import" in v for v in violations) == 2


def test_relative_imports_resolve_inside_the_package(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    ext = make_extension(
        tmp_path, files={"mod.py": "from . import helper\nfrom ..other import x\n"}
    )
    assert scan(gate, ext, write_policy(tmp_path)) == []


# ---------------------------------------------------------------------------
# policy validation
# ---------------------------------------------------------------------------


def test_policy_rejects_a_namespace_on_both_lists(gate: types.ModuleType, tmp_path: Path) -> None:
    path = write_policy(tmp_path, product_private_namespaces=["maistro_ext_sdk", "maistro"])
    with pytest.raises(SystemExit, match="both public SDK and product-private"):
        gate.load_policy(path)


def test_policy_requires_public_roots_and_trees(gate: types.ModuleType, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no public_sdk_namespaces"):
        gate.load_policy(write_policy(tmp_path, public_sdk_namespaces=[]))
    with pytest.raises(SystemExit, match="no extension_trees"):
        gate.load_policy(write_policy(tmp_path, extension_trees=[]))


def test_policy_must_classify_every_shipped_first_party_root(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    policy = gate.load_policy(write_policy(tmp_path))
    with pytest.raises(SystemExit, match=r"does not classify first-party import roots"):
        gate.check_policy_closure(policy, ROOT)


def test_unbuildable_extension_tree_is_a_policy_error(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "ext" / "not-a-project").mkdir(parents=True)
    policy = gate.load_policy(write_policy(tmp_path))
    with pytest.raises(SystemExit, match=r"no pyproject\.toml"):
        gate.discover_extensions(tmp_path, policy)


def test_tree_pattern_matching_nothing_is_a_policy_error(gate: types.ModuleType) -> None:
    real = gate.load_policy(REAL_POLICY)
    empty = types.SimpleNamespace(
        policy_version=real.policy_version,
        public_sdk_namespaces=real.public_sdk_namespaces,
        product_private_namespaces=real.product_private_namespaces,
        extension_trees=("extensions/does-not-exist/*",),
        test_only_namespaces=real.test_only_namespaces,
    )
    with pytest.raises(SystemExit, match="matched no directory"):
        gate.discover_extensions(ROOT, empty)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# the gate runs as a subprocess the way CI runs it
# ---------------------------------------------------------------------------


def test_gate_exits_zero_as_ci_runs_it() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "ok:" in result.stdout


# ---------------------------------------------------------------------------
# main() end-to-end over a fabricated root (no real-tree mutation needed)
# ---------------------------------------------------------------------------


def test_main_fails_and_names_violations_on_a_bad_tree(
    gate: types.ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_extension(tmp_path, files={"mod.py": "import maistro\n"})
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    assert gate.main([f"--policy={write_policy(tmp_path)}"]) == 1
    err = capsys.readouterr().err
    assert "product-private import" in err
    assert "FAIL: 1 extension import violation(s)" in err


def test_main_passes_on_a_clean_tree(
    gate: types.ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_extension(tmp_path, files={"mod.py": "import json\n"})
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    assert gate.main([f"--policy={write_policy(tmp_path)}"]) == 0
    assert "ok: 1 extension package(s)" in capsys.readouterr().out


def test_unreadable_or_invalid_policy_are_configuration_errors(
    gate: types.ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit, match="policy file not found"):
        gate.load_policy(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="not valid JSON"):
        gate.load_policy(broken)


def test_generated_and_cache_files_are_not_scanned(gate: types.ModuleType, tmp_path: Path) -> None:
    """A violation inside build output must not fail (or pass) the extension."""
    ext = make_extension(tmp_path, files={"mod.py": "import json\n"})
    junk = ext / "src" / "my_ext" / "__pycache__"
    junk.mkdir()
    (junk / "stale.py").write_text("import maistro\n", encoding="utf-8")
    (ext / "dist").mkdir()
    (ext / "dist" / "leak.py").write_text("import maistro\n", encoding="utf-8")
    assert scan(gate, ext, write_policy(tmp_path)) == []


def test_non_import_shapes_are_ignored(gate: types.ModuleType, tmp_path: Path) -> None:
    """Calls that merely resemble imports, and non-sys path mutations."""
    ext = make_extension(
        tmp_path,
        files={
            "mod.py": (
                "import importlib\n"
                "importlib.import_module()  # no target: not an import\n"
                "cache.path.append(x)  # not sys.path\n"
                "dynamic_import_module('x')  # not importlib\n"
            )
        },
    )
    assert scan(gate, ext, write_policy(tmp_path)) == []


def test_dynamic_import_aliases_are_resolved(gate: types.ModuleType, tmp_path: Path) -> None:
    """Alias bindings reach the real callables; unrelated methods stay calls."""
    ext = make_extension(
        tmp_path,
        files={
            "mod.py": (
                "from importlib import import_module as load\n"
                "import importlib as il\n"
                "load('maistro')\n"
                "il.import_module('maistro')\n"
                "manager.import_module('optional_plugin')\n"
            )
        },
    )
    violations = scan(gate, ext, write_policy(tmp_path))
    assert sum('dynamic import of "maistro"' in v for v in violations) == 2
    assert not any("optional_plugin" in v for v in violations)


def test_alias_bindings_respect_scope(gate: types.ModuleType, tmp_path: Path) -> None:
    """A binding inside one function is not the module's, and vice versa."""
    ext = make_extension(
        tmp_path,
        files={
            "mod.py": (
                "def f():\n"
                "    from importlib import import_module as load\n"
                "    load('maistro')\n"
                "\n"
                "def g():\n"
                "    import importlib as il\n"
                "    return il\n"
                "\n"
                "il.import_module('maistro')\n"
                "load('maistro')\n"
            )
        },
    )
    violations = scan(gate, ext, write_policy(tmp_path))
    assert len(violations) == 1
    assert ":3" in violations[0] and 'dynamic import of "maistro"' in violations[0]
