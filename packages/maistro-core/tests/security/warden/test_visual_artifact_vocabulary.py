"""The visual-artifact block vocabulary is one reviewed classification set (#817, #768).

`VISUAL_ARTIFACT_BLOCK_REASONS` names the reasons the Design Studio browser
boundary reports. The synchronous scanner (`scan_blocking_patterns` with
``visual_artifact=True`` — the same call the Design output boundary and the
trust pre-scan make) must only ever emit reasons from that same tuple, so an
admin-facing trust recommendation can never contradict what the renderer
blocks (AC-4).
"""

from __future__ import annotations

from maistro.security.warden.patterns import (
    VISUAL_ARTIFACT_BLOCK_REASONS,
    VISUAL_ARTIFACT_PATTERNS,
)


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
