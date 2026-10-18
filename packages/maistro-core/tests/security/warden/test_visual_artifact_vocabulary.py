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
    VISUAL_ARTIFACT_INERT_TAGS,
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
    # Several patterns may share one reason, but every declared reason must be
    # covered, first occurrence must keep the declared order, and no
    # undeclared reason may appear — a drift here means the derivation from
    # the declared tuple was bypassed. (The unknown-tag catch-all is code, not
    # a table row: visual_artifact_unknown_tag_names reuses
    # REASON_ACTIVE_ELEMENT from this same tuple.)
    seen: list[str] = []
    for _, reason in VISUAL_ARTIFACT_PATTERNS:
        if reason not in seen:
            seen.append(reason)

    assert tuple(seen) == VISUAL_ARTIFACT_BLOCK_REASONS
    assert {reason for _, reason in VISUAL_ARTIFACT_PATTERNS} == set(VISUAL_ARTIFACT_BLOCK_REASONS)


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


def _renderer_css_families() -> tuple[set[str], set[str]]:
    """Derive the primitive families from the renderer's NETWORK_OR_CODE_CSS.

    Returns (function families like ``url``/``var``, scheme families like
    ``data``/``javascript``) parsed straight from the TS regex literal, so a
    family added on the browser side shows up here without a manual list.
    """
    tsx = _monorepo_root() / _TS_RENDERER
    source = tsx.read_text(encoding="utf-8")
    match = re.search(r"const NETWORK_OR_CODE_CSS = /(.*?)/i;", source, re.DOTALL)
    assert match, "NETWORK_OR_CODE_CSS moved or was reshaped in the TS renderer"
    body = match.group(1)
    functions = set(re.findall(r"([@a-z][a-z0-9-]*)\\s\*\\\(", body))
    schemes = set(re.findall(r"([@a-z-][a-z0-9-]*)\\s\*:", body))
    return functions, schemes


def test_renderer_css_families_are_all_recognized_by_the_shared_scanner() -> None:
    """Pattern-body lockstep, not just reason-name lockstep (round-19 finding).

    The renderer's ``NETWORK_OR_CODE_CSS`` regex contained ``var()`` and
    ``env()`` families the shared scanner's CSS pattern never mirrored, so
    Chromium blocked ``<div style="color:var(--x)">`` with
    ``css-network-or-code`` while ``scan_and_record`` still recommended
    ``upgrade`` — the exact AC-4 contradiction #817 exists to prevent. This
    test derives every primitive family from the TS regex literal and requires
    the compiled Python CSS pattern to recognize each one, so neither side can
    grow a family the other lacks without a red test.
    """
    functions, schemes = _renderer_css_families()
    # Sanity on the derivation itself: the families this round drifted on must
    # be present, or the TS regex shape changed and this test needs updating.
    assert {"var", "env", "url", "expression"} <= functions, functions
    assert {"data", "javascript", "vbscript"} <= schemes, schemes

    css_pattern = next(
        pattern for pattern, reason in VISUAL_ARTIFACT_PATTERNS if reason == "css-network-or-code"
    )

    missing = []
    for family in sorted(functions):
        probe = f'<div style="width:{family}(1)">x</div>'
        if not css_pattern.search(probe):
            missing.append(family)
    for family in sorted(schemes):
        # Payload-bearing probe: the scanner deliberately value-anchors some
        # scheme families (``behavior:`` must name a payload so English prose
        # like "**Container behavior:**" stays renderable), so the probe names
        # a payload the way the blocked cases in test_scan.py do.
        probe = f'<div style="width:{family}://attacker.invalid/x">x</div>'
        if not css_pattern.search(probe):
            missing.append(family)
    assert not missing, (
        f"renderer blocks CSS primitive families the shared scanner does not classify: {missing}"
    )


def test_renderer_blocked_var_env_data_styles_are_scanner_blocked() -> None:
    """Regression: the exact round-19 parity probe must fail closed (#817)."""
    from maistro_design.scan import scan_blocking_patterns

    probes = (
        '<div style="color:var(--attacker-controlled)">y</div>',
        '<div style="padding:env(safe-area-inset-top)">y</div>',
        '<div style="background:data:text/html;base64,PHNjcmlwdD4=">y</div>',
    )
    for markup in probes:
        flags = scan_blocking_patterns("content", markup, None, visual_artifact=True)
        visual = [flag for flag in flags if "visual artifact " in flag]
        assert any(flag.endswith("css-network-or-code") for flag in visual), (
            f"{markup!r}: scanner did not classify a renderer-blocked style: {visual}"
        )


def _renderer_inert_tags() -> set[str]:
    """Parse the renderer's HTML_TAGS/SVG_TAGS inert sets from the TS source."""
    tsx = _monorepo_root() / _TS_RENDERER
    source = tsx.read_text(encoding="utf-8")
    tags: set[str] = set()
    for set_name in ("HTML_TAGS", "SVG_TAGS"):
        match = re.search(rf"const {set_name} = new Set\(\[(.*?)\]\);", source, re.DOTALL)
        assert match, f"{set_name} moved or was reshaped in the TS renderer"
        tags |= set(re.findall(r'"([^"]+)"', match.group(1)))
    return tags


def test_renderer_inert_tag_allowlist_is_pinned_by_python() -> None:
    """The catch-all's inert allowlist cannot drift from the browser boundary.

    ``scrubTree`` in visualArtifactRenderer.tsx blocks every element whose tag
    is outside HTML_TAGS/SVG_TAGS as ``active-element``. The shared scanner's
    catch-all classifies the same markup only if its allowlist is the same
    set; this test parses the TS sets and demands equality so neither side can
    grow or shrink a tag alone (#817 round-20 finding).
    """
    assert frozenset(_renderer_inert_tags()) == VISUAL_ARTIFACT_INERT_TAGS


def test_renderer_blocked_unknown_tags_are_scanner_classified_and_never_upgradeable() -> None:
    """Regression: the exact round-20 parity probe must fail closed (#817).

    The renderer removes `<marquee>` and every other non-allowlisted tag as
    ``active-element``; the pre-scan used to return empty flags and an
    ``upgrade`` recommendation for exactly that markup.
    """
    from maistro_design.scan import scan_blocking_patterns
    from maistro_design.trust import InMemoryTrustReviewQueue, TrustTier, scan_and_record

    probes = (
        "<marquee>hello</marquee>",
        "<custom-widget>hostile</custom-widget>",
        "<blink>x</blink>",
    )
    for markup in probes:
        flags = scan_blocking_patterns("content", markup, None, visual_artifact=True)
        visual = [flag for flag in flags if "visual artifact " in flag]
        assert any(flag.endswith("active-element") for flag in visual), (
            f"{markup!r}: scanner did not classify a renderer-blocked unknown tag: {flags}"
        )

        queue = InMemoryTrustReviewQueue()
        tier = scan_and_record(
            markup,
            source="discovery_field",
            source_key="k",
            record_id="r",
            review_queue=queue,
        )
        (record,) = queue.all_records()
        assert tier is TrustTier.SKULL, f"{markup!r}: pre-scan tier {tier}"
        assert record.warden_recommendation != "upgrade", (
            f"{markup!r}: pre-scan recommended upgrading renderer-blocked content"
        )


def test_inert_tags_stay_renderable_with_no_visual_flag() -> None:
    """Guard against an over-broad catch-all: allowlisted markup must stay clean.

    Case-insensitive tags, self-closing SVG shapes, prose comparisons like
    ``3 < 5``, and doctype/comment constructs are all inert in the browser and
    must produce no visual-artifact flag either.
    """
    from maistro_design.scan import scan_blocking_patterns

    inert = (
        "<div><p>ok</p></div>",
        '<svg viewBox="0 0 20 20"><circle cx="5" cy="5" r="4"/></svg>',
        "3 < 5 and x < y prose",
        "<TABLE><TR><TD>x</TD></TR></TABLE>",
        "<!DOCTYPE html><!-- review note -->",
    )
    for markup in inert:
        flags = scan_blocking_patterns("content", markup, None, visual_artifact=True)
        assert not [flag for flag in flags if "visual artifact " in flag], (
            f"{markup!r}: inert markup was flagged: {flags}"
        )
