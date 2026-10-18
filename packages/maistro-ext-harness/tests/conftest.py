"""Shared fabrication fixtures for the harness suite.

Every fabricated extension is written into a pytest tmp directory from a
manifest dict the test controls — the same `extension.json` + `src/` shape
the manifest contract pins, so a test exercises the format an author ships,
not an internal shortcut. Helpers live in fixtures (never imported as a
module) because the repository's pytest config runs `--import-mode=importlib`,
under which a conftest module import is exactly the checkout-relative rescue
extensions must not need.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

#: Repository root, derived from this file: packages/maistro-ext-harness/tests/
REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_EXTENSION = REPO_ROOT / "extensions" / "reference-greeter"

VALID_MANIFEST: dict[str, Any] = {
    "id": "acme.widget",
    "publisher": "acme",
    "version": "1.0.0",
    "title": "ACME widget",
    "description": "A minimal conforming tool extension used by the suite.",
    "contract": ">=1.0.0,<2.0.0",
    "family": "tool",
    "capabilities": [],
    "effects": ["read-only"],
    "data": {"scopes": []},
    "entrypoint": {"module": "acme_widget.plugin", "object": "PLUGIN"},
}

CONFORMING_PLUGIN = '''"""A conforming data-only tool extension."""

CALLS: list[str] = []

PLUGIN: dict[str, object] = {
    "kind": "tool",
    "name": "acme.widget",
    "version": "1.0.0",
    "capabilities": [],
    "handler": "spin",
}


def spin() -> str:
    CALLS.append("spin")
    return "spin-ok"


HANDLERS: dict[str, object] = {"spin": spin}
'''

RAISING_PLUGIN = '''"""A plugin whose handler always raises."""

PLUGIN: dict[str, object] = {
    "kind": "tool",
    "name": "acme.widget",
    "version": "1.0.0",
    "capabilities": [],
    "handler": "detonate",
}


def detonate() -> str:
    raise RuntimeError("fabricated handler failure")


HANDLERS: dict[str, object] = {"detonate": detonate}
'''

IMPORT_BOMB_PLUGIN = '''"""A plugin whose import proves whether code ran: validation must not run it."""

SENTINEL = __import__("pathlib").Path(__file__).parent / "bomb-detonated"
SENTINEL.write_text("extension code executed before validation", encoding="utf-8")

PLUGIN: dict[str, object] = {"kind": "tool", "handler": "missing"}
'''


def _materialize(
    root: Path,
    manifest: dict[str, Any],
    package: str,
    plugin_source: str,
) -> Path:
    src = root / "src" / package
    src.mkdir(parents=True, exist_ok=True)
    (root / "extension.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (src / "__init__.py").write_text(f'"""fabricated {package}."""\n', encoding="utf-8")
    (src / "plugin.py").write_text(plugin_source, encoding="utf-8")
    return root


@pytest.fixture
def valid_manifest() -> dict[str, Any]:
    """A fresh, valid manifest dict the test may mutate."""
    return dict(VALID_MANIFEST)


@pytest.fixture
def make_extension(tmp_path: Path) -> Callable[..., Path]:
    """Factory: write an extension under the test's tmp dir; returns its root."""

    def _make(
        *,
        name: str = "ext",
        manifest: dict[str, Any] | None = None,
        package: str = "acme_widget",
        plugin_source: str = CONFORMING_PLUGIN,
    ) -> Path:
        return _materialize(
            tmp_path / name,
            dict(manifest) if manifest is not None else dict(VALID_MANIFEST),
            package,
            plugin_source,
        )

    return _make


@pytest.fixture
def conforming_extension(make_extension: Callable[..., Path]) -> Path:
    return make_extension()


@pytest.fixture
def raising_extension(make_extension: Callable[..., Path]) -> Path:
    return make_extension(plugin_source=RAISING_PLUGIN)


IMPORT_BOMB_PLUGIN = '''"""A plugin whose import proves whether code ran."""

SENTINEL = __import__("pathlib").Path(__file__).parent / "bomb-detonated"
SENTINEL.write_text("extension code executed before validation", encoding="utf-8")

PLUGIN: dict[str, object] = {"kind": "tool", "handler": "missing"}
'''


@pytest.fixture
def import_bomb(
    make_extension: Callable[..., Path], valid_manifest: dict[str, Any]
) -> Callable[..., Path]:
    """An extension whose plugin writes a sentinel file at import time.

    The manifest ships broken (an unknown family), so validation has a real
    reason to reject it before the module could ever load.
    """

    def _make() -> Path:
        return make_extension(
            name="bomb",
            manifest={**valid_manifest, "family": "not-a-family"},
            plugin_source=IMPORT_BOMB_PLUGIN,
        )

    return _make
