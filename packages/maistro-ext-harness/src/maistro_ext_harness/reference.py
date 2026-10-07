"""The harness's built-in reference extension, materialized on demand (#974).

The issue's fourth acceptance criterion: the same test case must be able to
run against a reference built-in and an external implementation. The
reference subject here is a minimal, known-conforming `tool` extension the
harness itself writes into a directory — the same declarative shape as the
repository's `extensions/reference-greeter`, zero dependencies, data-only
entrypoint — so a third-party CI (which has no clone of the MAIstro
repository) still has a reference to compare against.

The materialized handler records its invocations in a module-level `CALLS`
list, which makes "the host never called the handler" observable — the
cancellation case's assertion.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = [
    "REFERENCE_EXTENSION_ID",
    "write_failing_probe_extension",
    "write_reference_extension",
]

REFERENCE_EXTENSION_ID = "harness.reference-tool"

_REFERENCE_PLUGIN = '''"""The reference extension's entrypoint: data plus one pure handler."""

CALLS: list[str] = []

PLUGIN: dict[str, object] = {
    "kind": "tool",
    "name": "harness.reference-tool",
    "version": "1.0.0",
    "capabilities": [],
    "handler": "greet",
}


def greet(target: str = "world") -> str:
    CALLS.append(target)
    return f"Hello, {target}!"


HANDLERS: dict[str, object] = {"greet": greet}
'''

_FAILING_PLUGIN = '''"""A probe whose handler always raises: the failure-containment fixture."""

PLUGIN: dict[str, object] = {
    "kind": "tool",
    "name": "harness.probe-failure",
    "version": "1.0.0",
    "capabilities": [],
    "handler": "detonate",
}


def detonate() -> str:
    raise RuntimeError("probe failure: deterministic, never a harness crash")


HANDLERS: dict[str, object] = {"detonate": detonate}
'''


def _manifest_json(ext_id: str, module: str, obj: str) -> str:
    manifest: dict[str, object] = {
        "id": ext_id,
        "publisher": ext_id.split(".")[0],
        "version": "1.0.0",
        "title": "Harness reference tool" if "reference" in ext_id else "Harness failure probe",
        "description": (
            "The host harness's own reference tool extension: the same case "
            "suite runs against this and against an external implementation."
            if "reference" in ext_id
            else "A probe whose handler raises deterministically, proving the "
            "host contains handler failures as typed results."
        ),
        "contract": ">=1.0.0,<2.0.0",
        "family": "tool",
        "capabilities": [],
        "effects": ["read-only"],
        "data": {"scopes": []},
        "entrypoint": {"module": module, "object": obj},
    }
    return json.dumps(manifest, indent=2) + "\n"


def _write_extension(dest: Path, ext_id: str, package: str, plugin_source: str) -> Path:
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"refusing to materialize over non-empty {dest}")
    src = dest / "src" / package
    src.mkdir(parents=True, exist_ok=True)
    (dest / "extension.json").write_text(
        _manifest_json(ext_id, f"{package}.plugin", "PLUGIN"), encoding="utf-8"
    )
    (src / "__init__.py").write_text(
        f'"""harness-materialized extension {ext_id}."""\n', encoding="utf-8"
    )
    (src / "plugin.py").write_text(plugin_source, encoding="utf-8")
    return dest


def write_reference_extension(dest: Path) -> Path:
    """Materialize the reference tool extension into `dest`; returns its root."""
    return _write_extension(
        dest, REFERENCE_EXTENSION_ID, "harness_reference_tool", _REFERENCE_PLUGIN
    )


def write_failing_probe_extension(dest: Path) -> Path:
    """Materialize the deterministic-failure probe into `dest`."""
    return _write_extension(dest, "harness.probe-failure", "harness_probe_failure", _FAILING_PLUGIN)
