"""The research and rsi-runner boot smokes cannot drift from what they prove (#346).

``scripts/smoke-engine-canvas.sh`` has ``tests/test_engine_canvas_packaging.py``
to hold its probe, its control image and its workflow invocations to the
contracts they claim. The two #346 gap-(b) smokes get the same discipline here,
so a rename, a softened probe or a dropped workflow step fails a test instead
of quietly shipping a smoke that proves nothing:

1. ci.yml's docker-build job still invokes both smokes against the images it
   just built (the port onto develop is the whole point of gap (b)).
2. The rsi smoke's ``PACKAGE_PATHS`` is exactly the operator contract's — the
   one ``tools/run_rsi_isolated.sh`` exports — parsed from both sources so
   neither can drift.
3. Each smoke's control image is the digest-pinned base its own Dockerfile
   builds from (the anti-cheat rule: a control that is not the image's own
   base can silently diverge from what the artifact actually ships), and the
   pinned reference is registered in ``quality/image-pins.json`` via
   ``tests/test_pinned_digest_references.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH_SMOKE = ROOT / "scripts" / "smoke-research-chromium.sh"
RSI_SMOKE = ROOT / "scripts" / "smoke-rsi-runner-imports.sh"
RSI_CONTRACT = ROOT / "tools" / "run_rsi_isolated.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"

PINNED_REF = re.compile(r"\b([a-z0-9._/-]+):([A-Za-z0-9._-]+)@sha256:([0-9a-f]{64})")


def _first_from(dockerfile: Path) -> str:
    """The first FROM line's pinned base reference."""
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("FROM "):
            refs = PINNED_REF.findall(stripped)
            assert refs, f"{dockerfile.name} first FROM is not digest-pinned: {stripped}"
            image, tag, digest = refs[0]
            return f"{image}:{tag}@{digest}"
    raise AssertionError(f"{dockerfile.name} has no FROM line")


def test_ci_still_runs_both_smokes() -> None:
    """The docker-build job proves the two images it builds, not just builds them."""
    ci = CI.read_text(encoding="utf-8")
    assert "scripts/smoke-research-chromium.sh maistro-engine-research:ci" in ci, (
        "ci.yml lost the research image's chromium smoke invocation (#346 gap (b))"
    )
    assert "scripts/smoke-rsi-runner-imports.sh maistro-rsi-runner:ci" in ci, (
        "ci.yml lost the rsi-runner image's import smoke invocation (#346 gap (b))"
    )


def test_rsi_smoke_mirrors_the_operator_contract_paths() -> None:
    """The smoke's PYTHONPATH is the operator contract's, verbatim.

    The root meta-package does not install maistro-rsi or maistro-evolve, so
    the source trees on PYTHONPATH are load-bearing: the loop's entrypoints
    import from them. If either side of this contract drifts, the smoke stops
    proving the runtime the operator actually drives.
    """

    def package_paths(text: str) -> str:
        match = re.search(r'^PACKAGE_PATHS="([^"]+)"', text, flags=re.MULTILINE)
        assert match, "lost the PACKAGE_PATHS literal"
        return match.group(1)

    smoke = package_paths(RSI_SMOKE.read_text(encoding="utf-8"))
    contract = package_paths(RSI_CONTRACT.read_text(encoding="utf-8"))
    assert smoke == contract, (
        "the rsi smoke's PACKAGE_PATHS drifted from tools/run_rsi_isolated.sh: "
        f"{smoke!r} != {contract!r}"
    )


def test_research_control_image_is_the_dockerfiles_own_base() -> None:
    """The chromium smoke's control is the base Dockerfile.research builds from.

    A control image that is not the artifact's own base can diverge from what
    the image actually ships, and a control that passes the probe would mean
    the probe has no teeth.
    """
    refs = PINNED_REF.findall(RESEARCH_SMOKE.read_text(encoding="utf-8"))
    assert refs, "research smoke lost its digest-pinned control image"
    control = refs[0]
    assert f"{control[0]}:{control[1]}@{control[2]}" == _first_from(ROOT / "Dockerfile.research"), (
        "the research smoke's control image drifted from Dockerfile.research's base"
    )


def test_rsi_control_image_is_the_dockerfiles_own_base() -> None:
    """The import smoke's control is the base Dockerfile.rsi-runner builds from."""
    refs = PINNED_REF.findall(RSI_SMOKE.read_text(encoding="utf-8"))
    assert refs, "rsi smoke lost its digest-pinned control image"
    control = refs[0]
    assert f"{control[0]}:{control[1]}@{control[2]}" == _first_from(
        ROOT / "Dockerfile.rsi-runner"
    ), "the rsi smoke's control image drifted from Dockerfile.rsi-runner's base"
