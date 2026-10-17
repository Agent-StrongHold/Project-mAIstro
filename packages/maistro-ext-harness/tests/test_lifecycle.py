"""The lifecycle simulation: order, containment, cancellation, release (#974)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from maistro_ext_harness import (
    EntrypointMissing,
    ExtensionHost,
    HandlerRaised,
    InvocationCancelled,
    ManifestRejected,
    SubjectNotDiscovered,
)


def _load(root: Path) -> tuple[ExtensionHost, object, object, object]:
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    grant = host.grants_for(manifest)
    return host, discovered, manifest, host.load(discovered, manifest, grant)


def test_discover_requires_a_manifest(tmp_path: Path) -> None:
    with pytest.raises(SubjectNotDiscovered, match=r"no extension\.json"):
        ExtensionHost().discover(tmp_path)
    with pytest.raises(SubjectNotDiscovered, match="not a directory"):
        ExtensionHost().discover(tmp_path / "absent")


def test_validation_precedes_any_extension_code(import_bomb: Callable[..., Path]) -> None:
    """The import bomb: its plugin writes a sentinel file at import time.

    Validation must reject the broken manifest without the module ever
    loading — the sentinel proves whether extension code ran.
    """
    root = import_bomb()
    host = ExtensionHost()
    discovered = host.discover(root)
    with pytest.raises(ManifestRejected):
        host.validate(discovered)
    sentinel = root / "src" / "acme_widget" / "bomb-detonated"
    assert not sentinel.exists(), "extension code executed before validation"


def test_load_stage_is_the_first_code_that_runs(
    tmp_path: Path, valid_manifest: dict, import_bomb: Callable[..., Path]
) -> None:
    root = import_bomb()
    # Fix the manifest so validation passes; only the load stage may detonate.
    (root / "extension.json").write_text(json.dumps(valid_manifest), encoding="utf-8")
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    grant = host.grants_for(manifest)
    loaded = host.load(discovered, manifest, grant)
    host.release(loaded)
    assert (root / "src" / "acme_widget" / "bomb-detonated").exists()


def test_missing_entrypoint_object_is_typed(
    valid_manifest: dict, make_extension: Callable[..., Path]
) -> None:
    # A distinct package name: this test deliberately leaves its module in
    # sys.modules (the load failed before a release was possible), and a
    # shared name would leak the cached conforming module into later tests.
    manifest = {
        **valid_manifest,
        "entrypoint": {"module": "absent_obj.plugin", "object": "ABSENT"},
    }
    root = make_extension(manifest=manifest, package="absent_obj")
    host = ExtensionHost()
    discovered = host.discover(root)
    loaded_manifest = host.validate(discovered)
    grant = host.grants_for(loaded_manifest)
    with pytest.raises(EntrypointMissing, match="ABSENT"):
        host.load(discovered, loaded_manifest, grant)


def test_handler_failure_is_contained_with_cause(raising_extension: Path) -> None:
    host, _discovered, _manifest, loaded = _load(raising_extension)
    try:
        with pytest.raises(HandlerRaised) as excinfo:
            host.invoke(loaded)
        assert isinstance(excinfo.value.__cause__, RuntimeError)
        # The host stays usable: a second invoke still raises the typed error,
        # it does not crash the host.
        with pytest.raises(HandlerRaised):
            host.invoke(loaded)
    finally:
        host.release(loaded)


def test_cancellation_refuses_the_call_before_the_handler_runs(
    make_extension: Callable[..., Path], valid_manifest: dict
) -> None:
    root = make_extension(manifest={**valid_manifest, "capabilities": ["run.read"]})
    host, _discovered, _manifest, loaded = _load(root)
    try:
        loaded.request_cancel()
        assert loaded.context.invocation is not None
        assert loaded.context.invocation.cancel_requested is True
        with pytest.raises(InvocationCancelled):
            host.invoke(loaded)
        assert loaded.module.CALLS == [], "handler ran despite cancellation"
    finally:
        host.release(loaded)


def test_release_evicts_the_extension_modules(make_extension: Callable[..., Path]) -> None:
    root = make_extension()
    host, _discovered, _manifest, loaded = _load(root)
    prefix = loaded.module.__name__.split(".")[0]
    host.release(loaded)
    assert not [name for name in sys.modules if name.startswith(prefix + ".")]


def test_handlers_with_a_first_parameter_receive_the_context(
    make_extension: Callable[..., Path],
) -> None:
    """The M9-A2 bridge: a handler whose signature declares a first parameter
    gets the context object; the reference zero-argument shape keeps working."""
    plugin = """
PLUGIN: dict[str, object] = {"kind": "tool", "handler": "observe"}

_SEEN: list[object] = []


def observe(context: object) -> str:
    _SEEN.append(context)
    return "observed"


HANDLERS: dict[str, object] = {"observe": observe}
"""
    root = make_extension(plugin_source=plugin)
    host, _discovered, _manifest, loaded = _load(root)
    try:
        result = host.invoke(loaded)
        assert result == "observed"
        seen = loaded.module._SEEN
        assert len(seen) == 1
        assert seen[0] is loaded.context
    finally:
        host.release(loaded)
