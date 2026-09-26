"""The visual-artifact block vocabulary is one reviewed classification set (#817, #768).

`VISUAL_ARTIFACT_BLOCK_REASONS` names the reasons the Design Studio browser
boundary reports. The synchronous scanner (`scan_blocking_patterns` with
``visual_artifact=True`` — the same call the Design output boundary and the
trust pre-scan make) must only ever emit reasons from that same tuple, so an
admin-facing trust recommendation can never contradict what the renderer
blocks (AC-4).
"""

from __future__ import annotations

import re
from pathlib import Path

from maistro.security.warden.patterns import (
    VISUAL_ARTIFACT_BLOCK_REASONS,
    VISUAL_ARTIFACT_PATTERNS,
)

_TS_RENDERER = Path("packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx")


def _monorepo_root() -> Path:
    """Locate the checkout root that holds both vocabulary sides."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages/maistro-core").is_dir() and (
            parent / "packages/hive-conductor"
        ).is_dir():
            return parent
    raise AssertionError("monorepo root with packages/maistro-core + hive-conductor not found")


def test_pattern_table_reasons_are_the_declared_vocabulary() -> None:
    reasons = tuple(reason for _, reason in VISUAL_ARTIFACT_PATTERNS)

    # Same names, same order: the table is derived from the declared tuple, so
    # a drift here means the derivation was bypassed.
    assert reasons == VISUAL_ARTIFACT_BLOCK_REASONS
    assert len(set(reasons)) == len(reasons)


def test_design_scanner_emits_only_declared_visual_reasons() -> None:
    # One hostile probe per declared reason family; the scanner's visual
    # layer must classify each with a declared reason and nothing else.
    from maistro_design.scan import scan_blocking_patterns

    probes = {
        "active-element": "<svg><script>alert(1)</script></svg>",
        "event-handler": '<img src=x onerror="alert(1)">',
        "dangerous-url": '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
        "css-network-or-code": '<div style="background:url(http://evil.example/x)">y</div>',
    }
    for reason, markup in probes.items():
        flags = scan_blocking_patterns("content", markup, None, visual_artifact=True)
        visual_flags = [flag for flag in flags if "visual artifact " in flag]
        assert visual_flags, f"{reason}: probe produced no visual-artifact flag: {flags}"
        assert any(flag.endswith(f"visual artifact {reason}") for flag in visual_flags), (
            f"{reason}: expected a declared visual-artifact flag, got {visual_flags}"
        )
        emitted = {flag.split("visual artifact ", 1)[1].split(" ", 1)[0] for flag in visual_flags}
        assert emitted <= set(VISUAL_ARTIFACT_BLOCK_REASONS), (
            f"{reason}: scanner emitted undeclared reasons {emitted - set(VISUAL_ARTIFACT_BLOCK_REASONS)}"
        )


def test_typescript_renderer_mirror_equals_declared_vocabulary() -> None:
    """AC-4 across the language boundary, enforced rather than comment-anchored.

    The browser boundary keeps its own copy of the reason names (a TS `as const`
    array in ``visualArtifactRenderer.tsx``, historically held in lockstep only
    by a source comment). This test parses that constant and demands equality —
    same names, same order — with Warden's declared tuple, so neither side can
    drift without a red test.
    """
    tsx = _monorepo_root() / _TS_RENDERER
    assert tsx.is_file(), f"TS mirror moved/renamed without updating this lockstep test: {tsx}"
    source = tsx.read_text(encoding="utf-8")
    match = re.search(
        r"export const VISUAL_ARTIFACT_BLOCK_REASONS\s*=\s*\[(.*?)\]\s*as const",
        source,
        re.DOTALL,
    )
    assert match, (
        "VISUAL_ARTIFACT_BLOCK_REASONS no longer declared as an 'as const' string "
        "array in the TS renderer; the mirrored constant was reshaped"
    )
    ts_reasons = re.findall(r'"([^"]+)"', match.group(1))
    assert ts_reasons == list(VISUAL_ARTIFACT_BLOCK_REASONS), (
        f"TS/Python vocabulary drift: TS={ts_reasons} Python={list(VISUAL_ARTIFACT_BLOCK_REASONS)}"
    )
