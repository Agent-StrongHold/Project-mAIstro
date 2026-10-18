"""The shipped engine image carries the Canvas surface it advertises (#1825).

The engine mounts ``/v2/canvas`` unconditionally, but until #1825 its
dependency install omitted ``maistro-canvas``: ``_wire_canvas_ability()`` hit
``ImportError`` at startup, left ``app.state.canvas_store`` unset, and every
Canvas route answered 503 forever — invisible to a healthy API container, a
monorepo test environment (``uv sync`` installs everything), or
``/health/live``. Three layers of proof, cheapest first:

1. **Static packaging gate** (no Docker, runs on every PR): the root
   Dockerfile's builder stage must COPY and pip-install ``maistro-canvas``,
   and the workflows must still invoke the smoke script. Removing Canvas from
   the supported artifact definition fails here first.

2. **Artifact probe** (Docker; opt-in via ``MAISTRO_ENGINE_IMAGE``): the exact
   import the shipped server makes, executed in a container with
   ``--network=none``, no mounts and no PYTHONPATH — so only image contents
   can satisfy it. The probe text is extracted from
   ``scripts/smoke-engine-canvas.sh`` itself, so this test cannot drift from
   what CI runs. The negative control runs the same probe against the
   Dockerfile's pinned builder base and must FAIL: the probe detects a
   Canvas-less artifact even while this repository workspace has every
   package installed, because the container never sees the workspace.

3. **Full boot smoke** (Docker; also set ``MAISTRO_ENGINE_IMAGE_SMOKE=1``):
   runs ``scripts/smoke-engine-canvas.sh`` end to end — clean PostgreSQL 18
   volume, migration through the authoritative shipped entrypoint,
   ``canvas_store_wired`` cannot (the production log level filters that
   info event out), so the wiring proof is behavioral: an authenticated
   Canvas create/read through ``/v2/canvas``, an unauthenticated request
   refused, and the row verified in PostgreSQL itself, plus the tested image
   digest printed. This is the same script ci.yml's
   ``docker-build`` job runs on the built candidate and release.yml's
   ``images`` job runs against the exact pushed digest before signing it.

Without ``MAISTRO_ENGINE_IMAGE`` the Docker layers skip with instructions —
the same contract as ``MAISTRO_TEST_PG_DSN`` — and layer 1 still holds the
tree. The default ``pytest`` run stays hermetic; the artifact-level proof
lives where the artifact exists (ci.yml ``docker-build``).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
SMOKE_SCRIPT = ROOT / "scripts" / "smoke-engine-canvas.sh"

#: The builder stage is everything from the first FROM to the next top-level
#: FROM (the runtime stage). The dependency install that must include
#: maistro-canvas lives in the builder; a runtime-stage-only install would
#: never reach the shipped venv.
_STAGE_SPLIT = re.compile(r"^FROM ", re.M)


def _stages() -> list[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    starts = [m.start() for m in _STAGE_SPLIT.finditer(text)]
    return [text[a:b] for a, b in zip(starts, [*starts[1:], None], strict=False)]


def _builder_stage() -> str:
    stages = _stages()
    assert stages, "Dockerfile lost every FROM line"
    builder = stages[0]
    assert "AS builder" in builder, "the first Dockerfile stage is no longer the builder"
    return builder


def _canvas_probe() -> str:
    """The probe exactly as the smoke script runs it — one source of truth."""
    match = re.search(r"CANVAS_PROBE='(.*?)'\n", SMOKE_SCRIPT.read_text(encoding="utf-8"), re.S)
    assert match, (
        "scripts/smoke-engine-canvas.sh lost its CANVAS_PROBE literal; "
        "the artifact probe has nothing to run"
    )
    return match.group(1)


def _control_image() -> str:
    """The Canvas-less control image the smoke script defaults to."""
    match = re.search(
        r'^CONTROL_IMAGE="\$\{2:-(.+)\}"\n', SMOKE_SCRIPT.read_text(encoding="utf-8"), re.M
    )
    assert match, "smoke script lost its CONTROL_IMAGE default"
    return match.group(1)


def _docker_available() -> str | None:
    """Return a skip reason when Docker cannot run a container here."""
    if shutil.which("docker") is None:
        return "docker CLI is not on PATH"
    probe = subprocess.run(
        ["docker", "info", "--format", "ok"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if probe.returncode != 0:
        return f"docker daemon is unreachable: {probe.stderr.strip()[:200]}"
    return None


# ── Layer 1: static packaging gate (no Docker, every PR) ─────────────────


def test_builder_stage_copies_and_installs_maistro_canvas() -> None:
    builder = _builder_stage()
    assert "COPY packages/maistro-canvas packages/maistro-canvas" in builder, (
        "the builder stage no longer copies maistro-canvas; the shipped engine "
        "image would boot with /v2/canvas answering 503 forever (#1825)"
    )
    install_start = builder.find("RUN pip install --no-cache-dir")
    assert install_start != -1, "the builder stage lost its pip install RUN line"
    install_block = builder[install_start:]
    # A RUN block runs until the first blank line; keep the search inside it so
    # a later, unrelated instruction cannot satisfy the assertion.
    block_end = install_block.find("\n\n")
    if block_end != -1:
        install_block = install_block[:block_end]
    assert '"./packages/maistro-canvas"' in install_block, (
        "the builder's pip install no longer includes maistro-canvas; a COPY "
        "without the install puts source in the context but nothing in the venv"
    )


def test_the_workflows_still_run_the_canvas_smoke() -> None:
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/smoke-engine-canvas.sh maistro-engine:test" in ci, (
        "ci.yml no longer proves the built engine image ships its Canvas surface"
    )
    release = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert (
        'scripts/smoke-engine-canvas.sh "${IMAGE_NAMESPACE}/maistro-engine@${ENGINE_DIGEST}"'
        in release
    ), (
        "release.yml no longer consumes the Canvas proof against the exact "
        "digest it signs and publishes"
    )


def test_smoke_control_image_is_the_dockerfiles_own_base() -> None:
    """The control image must be the engine's pinned builder base.

    That base is exactly "the same artifact definition minus every project
    package", so if it ever imported maistro-canvas, the negative control
    would be proving nothing. Parsing both from their sources keeps them from
    drifting apart.
    """
    from_line = re.search(r"^FROM (\S+)", DOCKERFILE.read_text(encoding="utf-8"), re.M)
    assert from_line, "the Dockerfile lost its first FROM line"
    assert _control_image() == from_line.group(1), (
        "the smoke's Canvas-less control image drifted from the Dockerfile's "
        "pinned builder base; re-pin them together"
    )


def test_smoke_script_asserts_the_isolation_and_the_wiring() -> None:
    """The markers that make the smoke a Canvas proof rather than a boot check."""
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "--network=none" in script, (
        "the import probe must run without a network so no dependency can be "
        "fetched into the container at proof time"
    )
    for import_line in (
        "from maistro_canvas.canvas.store import PgCanvasStore",
        "from maistro_canvas.canvas.compositor import PilCompositorService",
    ):
        assert import_line in script, f"the probe no longer asserts {import_line}"
    assert "canvas_store_unavailable" in script, (
        "the boot smoke must refuse the 503-unavailable branch, not just miss it"
    )
    assert not re.search(r"grep -q canvas_store_wired", script), (
        "the smoke must not gate on canvas_store_wired: structlog runs at "
        "WARNING in the shipped image, so that info event never renders and "
        "the grep could only false-negative"
    )
    assert "SELECT name FROM canvases" in script, (
        "the smoke must verify the write landed in PostgreSQL through the "
        "real store, not merely that the API answered"
    )
    assert "/v2/canvas/designs" in script, "the smoke must exercise the Canvas API surface"
    assert "Authorization: Bearer smoke-access-token" in script, (
        "the Canvas create/read must be authenticated"
    )
    assert re.search(r"401.*403|403.*401", script), (
        "the smoke must prove an unauthenticated Canvas write is refused"
    )


# ── Layer 2: artifact probe (Docker, opt-in) ─────────────────────────────


@pytest.fixture(scope="module")
def engine_image() -> str:
    reason = _docker_available()
    image = os.environ.get("MAISTRO_ENGINE_IMAGE", "")
    if image:
        assert reason is None, f"MAISTRO_ENGINE_IMAGE is set but {reason}"
    else:
        pytest.skip(
            "MAISTRO_ENGINE_IMAGE is unset; point it at a built engine image "
            "(e.g. maistro-engine:test from ci.yml's docker-build job) to run "
            "the artifact-level Canvas proof"
        )
    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert inspect.returncode == 0, (
        f"MAISTRO_ENGINE_IMAGE={image!r} is not a local image: {inspect.stderr.strip()[:300]}"
    )
    return image


def _run_probe(image: str) -> subprocess.CompletedProcess[str]:
    """The probe in the exact isolation the smoke script uses.

    No network, no mounts, no inherited environment beyond docker's own: an
    import satisfied here is satisfied by image contents alone, whatever the
    repository workspace has installed.
    """
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint",
            "python",
            image,
            "-c",
            _canvas_probe(),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_built_engine_image_imports_the_canvas_store(engine_image: str) -> None:
    result = _run_probe(engine_image)
    assert result.returncode == 0, (
        f"the built engine image cannot import the Canvas store on its own "
        f"contents — the #1825 omission is back:\n{result.stderr[-800:]}"
    )
    assert "PgCanvasStore" in result.stdout, (
        f"the probe ran but did not reach PgCanvasStore:\n{result.stdout[-400:]}"
    )


def test_the_probe_fails_on_a_canvas_less_artifact(engine_image: str) -> None:
    """The negative control: the probe must detect a Canvas-less image.

    Run against the Dockerfile's own pinned base — the same artifact
    definition minus every project package. The workspace's installation of
    maistro-canvas is invisible in there (no mounts, no PYTHONPATH), which is
    exactly the point: this is the failure the positive test would produce if
    Canvas were dropped from the image, so a probe that stopped detecting it
    fails here first.
    """
    result = _run_probe(_control_image())
    assert result.returncode != 0, (
        "the Canvas-less control image imported maistro-canvas; the probe has "
        "lost its teeth and the positive result proves nothing"
    )
    combined = result.stdout + result.stderr
    assert "No module named" in combined or "ModuleNotFoundError" in combined, (
        f"the control failed for an unexpected reason (probe bug?), not a "
        f"missing module:\n{combined[-600:]}"
    )


# ── Layer 3: the full shipped smoke (Docker, doubly opt-in) ──────────────


def test_full_canvas_smoke_runs_against_a_built_image(engine_image: str) -> None:
    if not os.environ.get("MAISTRO_ENGINE_IMAGE_SMOKE"):
        pytest.skip(
            "MAISTRO_ENGINE_IMAGE_SMOKE is unset; set it to run the complete "
            "boot + authenticated Canvas CRUD smoke (pulls pgvector/pgvector:pg18)"
        )
    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT), engine_image],
        capture_output=True,
        text=True,
        timeout=1500,
        check=False,
    )
    assert result.returncode == 0, (
        f"the shipped-image Canvas smoke failed against {engine_image}:\n"
        f"--- stdout tail ---\n{result.stdout[-1500:]}\n"
        f"--- stderr tail ---\n{result.stderr[-1500:]}"
    )
    assert f"smoke-engine-canvas: PASS ({engine_image})" in result.stdout
