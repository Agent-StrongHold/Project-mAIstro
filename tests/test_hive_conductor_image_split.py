"""The Conductor image's builder/runtime base split is a pinned contract.

#2304 moved the Conductor image's runtime OS layer to
`python:3.15.0-slim-bookworm` while the app keeps running on the registered
CPython 3.13.16 build: the `pybuild` stage keeps the 3.13.16 pin (coincurve
21.0.0 publishes `cp313` wheels only, and the build smoke asserts the exact
interpreter version), and the final stage grafts pybuild's CPython
installation (binary, libpython, stdlib) so the copied venv's interpreter
symlinks resolve without a managed download. Both bases are Debian 12, so the
grafted binary runs against the glibc it was built against.

These tests hold that structure closed. A future edit that bumps the builder
off the contract pin, moves the runtime to an unregistered digest, or drops
the graft would ship an image whose venv interpreter is missing -- or silently
downloaded at build time -- and that must be a red test here, not a red
runtime discovered by the e2e stack or, worse, a silent interpreter change of
exactly the kind the Dockerfile header forbids.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "packages" / "hive-conductor" / "Dockerfile"
PINS_PATH = ROOT / "quality" / "image-pins.json"

#: `FROM <ref> AS <stage>` — the same shape every stage declaration takes.
_STAGE_FROM = re.compile(r"^FROM (?P<ref>\S+) AS (?P<stage>\S+)$", re.MULTILINE)

#: `COPY --from=pybuild <src> <dst>` — the graft's interpreter plumbing.
_GRAFT_COPY = re.compile(r"^COPY --from=pybuild (?P<src>\S+) (?P<dst>\S+)$", re.MULTILINE)


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _stage_refs() -> dict[str, str]:
    """Map every `AS <stage>` name to its `name:tag@sha256:<digest>` ref."""
    return {m.group("stage"): m.group("ref") for m in _STAGE_FROM.finditer(_dockerfile())}


def _registry_row(name_tag: str) -> dict:
    rows = json.loads(PINS_PATH.read_text(encoding="utf-8"))["pins"]
    return next(row for row in rows if f"{row['image']}:{row['tag']}" == name_tag)


def test_pybuild_stays_on_the_registered_contract_pin() -> None:
    """The builder stage IS the identity contract and must stay on its row."""
    row = _registry_row("python:3.13.16-slim-bookworm")
    assert _stage_refs()["pybuild"] == f"python:3.13.16-slim-bookworm@{row['digest']}"
    assert "packages/hive-conductor/Dockerfile" in row["used_by"]
    # The contract venv is created from the builder's system interpreter, so
    # `uv venv --python 3.13` must keep resolving it (not a managed download):
    assert "uv venv --python 3.13 /app/venv" in _dockerfile()


def test_runtime_os_layer_is_registered_and_not_the_builder_base() -> None:
    """The OS layer carries dependabot's bump, registered in its own row."""
    refs = _stage_refs()
    row = _registry_row("python:3.15.0-slim-bookworm")
    assert refs["runtime-apt"] == f"python:3.15.0-slim-bookworm@{row['digest']}"
    assert "packages/hive-conductor/Dockerfile" in row["used_by"]
    # The split is the point: OS layer and contract interpreter are two
    # different registered builds, on purpose (see the stage comments).
    assert refs["runtime-apt"] != refs["pybuild"]


def test_the_runtime_grafts_the_interpreter_the_venv_links() -> None:
    """The venv's interpreter symlinks must resolve inside the shipped stage.

    On the pre-#2304 image both stages shared one base, so `/usr/local/bin/
    python3.13` existed everywhere by construction. With the runtime on the
    3.15 base the builder's exact CPython installation must be grafted in, or
    the copied venv has no interpreter at all.
    """
    final_stage = _dockerfile().split("FROM runtime-apt", 1)[1]
    grafted_sources = {m.group("src") for m in _GRAFT_COPY.finditer(final_stage)}
    assert {
        "/usr/local/bin/python3.13",
        "/usr/local/lib/libpython3.13.so.1.0",
        "/usr/local/lib/python3.13",
    } <= grafted_sources
    # The grafted shared library must be registered the way the base image
    # registers its own, or the interpreter fails on startup, not at build.
    assert re.search(r"^RUN ldconfig$", final_stage, re.MULTILINE)


def test_the_build_smoke_still_pins_the_contract_version_and_identity() -> None:
    """The split must not drift the build-time identity assertions."""
    text = _dockerfile()
    assert "assert sys.version_info[:3] == (3, 13, 16)" in text
    for arg in (
        "ARG BIP_UTILS_VERSION=2.12.2",
        "ARG COINCURVE_VERSION=21.0.0",
        "ARG PYNACL_VERSION=1.6.2",
    ):
        assert arg in text
