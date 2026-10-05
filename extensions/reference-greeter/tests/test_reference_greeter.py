"""The reference extension's self-contract tests.

These run in the isolated venv the CI fixture builds (a fresh environment
holding only this wheel and pytest), so they may import nothing but this
package, the standard library, and pytest. That constraint IS the test: any
product-private or repo-relative import fails here with an ImportError before
an assertion can even run.
"""

from __future__ import annotations

import importlib
import json
import sys
from importlib.resources import files as resource_files
from pathlib import Path

import reference_greeter


def _manifest() -> dict[str, object]:
    # A host discovers an extension through the ``extension.json`` its wheel
    # ships, so the installed distribution is what this suite reads first.
    try:
        text = (
            resource_files("reference_greeter")
            .joinpath("extension.json")
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        # The root dev environment installs this extension editable, and an
        # editable install maps only the package directory: the manifest
        # lives at the extension root and ``force-include`` maps it into the
        # wheel. There the extension root's copy is read instead. In the
        # isolation fixture the staged suite has no such sibling file, so
        # the fallback cannot exist there — if the wheel dropped the
        # manifest, these tests cannot run, and the fixture's artifact check
        # names the missing file before the suite even starts.
        text = (Path(__file__).resolve().parents[1] / "extension.json").read_text(encoding="utf-8")
    return json.loads(text)


def test_manifest_declares_least_authority() -> None:
    manifest = _manifest()
    assert manifest["capabilities"] == []
    assert manifest["effects"] == ["read-only"]
    assert manifest["data"] == {"scopes": []}


def test_manifest_identity_and_contract_are_well_formed() -> None:
    manifest = _manifest()
    # ``publisher.name`` — the id names its publisher by construction.
    assert str(manifest["id"]).startswith(f"{manifest['publisher']}.")
    # The contract range pins the manifest schema major the extension codes
    # against. Pinning the major (and excluding the next) is what lets a host
    # reject an unreviewable manifest instead of guessing.
    contract = str(manifest["contract"])
    assert contract.startswith(">=") and ",<" in contract
    low, high = contract.removeprefix(">=").split(",<")
    # A range that pins one major excludes exactly the next: >=1,<2 — never
    # a span across two majors claiming compatibility with a schema that does
    # not exist yet.
    assert high.split(".")[0] == str(int(low.split(".")[0]) + 1), (
        "the contract range must pin exactly the next major boundary"
    )


def test_manifest_entrypoint_resolves_to_a_real_object() -> None:
    manifest = _manifest()
    entrypoint = manifest["entrypoint"]
    assert isinstance(entrypoint, dict)
    module = importlib.import_module(str(entrypoint["module"]))
    plugin = getattr(module, str(entrypoint["object"]))
    assert plugin["kind"] == manifest["family"]
    assert plugin["name"] == manifest["id"]
    assert plugin["version"] == manifest["version"]


def test_declared_handler_exists_and_is_pure() -> None:
    from reference_greeter import plugin as plugin_module

    plugin = plugin_module.PLUGIN
    handler = plugin_module.HANDLERS[str(plugin["handler"])]
    assert callable(handler)
    assert handler("M9") == "Hello, M9!"


def test_the_package_imports_nothing_first_party() -> None:
    """The structural form of acceptance criterion 3 and 4 (#951): the
    reference extension depends on no first-party module at all, so product
    internals can change without ever touching it."""
    import ast

    package_root = Path(reference_greeter.__file__).resolve().parent
    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                assert not root.startswith("maistro"), (
                    f"{path.name} imports first-party module {root!r}"
                )
            assert roots == [] or all(
                root in sys.stdlib_module_names or root == "reference_greeter" for root in roots
            ), f"{path.name} imports an undeclared dependency: {roots}"
