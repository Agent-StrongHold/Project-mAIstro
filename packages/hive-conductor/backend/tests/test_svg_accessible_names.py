"""A named chart svg must declare the image role its name depends on (#1432).

An `<svg>` element is not mapped to the image role by browsers by default, so
an `aria-label` on a bare `<svg>` is not reliably exposed to assistive
technology (WCAG 4.1.2 Name, Role, Value; 1.1.1 Non-text Content). The audit's
A11Y-11 finding was exactly that shape: `SvgDonut.tsx` labelled its donut
chart without giving the element a role.

The component currently has no importers, so no rendered-page test can reach
it; these assertions read the frontend sources the way `test_csp.py` does —
one exact pin on the audited component, plus one invariant over every named
svg in the app so the next chart cannot reintroduce the gap.
"""

from __future__ import annotations

import pathlib
import re

_FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

#: `role="img"`, `role='img'`, or `role={"img"}` — the spellings JSX accepts.
_ROLE_IMG = re.compile(r"role\s*=\s*(?:\{\s*[\"']img[\"']\s*\}|[\"']img[\"'])")


def _svg_opening_tags(source: str) -> list[str]:
    """Return every `<svg …>` opening tag in *source*.

    JSX attribute values may legitimately contain `>` — an arrow function in
    an event handler, a comparison inside an expression — so a bare "scan to
    the next `>`" misparses the interactive-diagram tags. The scanner instead
    skips quoted strings and tracks brace depth, ending the tag at the first
    `>` that is outside both.
    """
    tags: list[str] = []
    start = source.find("<svg")
    while start != -1:
        i = start + len("<svg")
        quote: str | None = None
        depth = 0
        end: int | None = None
        while i < len(source):
            ch = source[i]
            if quote is not None:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(depth - 1, 0)
            elif ch == ">" and depth == 0:
                end = i + 1
                break
            i += 1
        if end is None:  # unterminated tag: the rest of the file is the tag
            end = len(source)
        tags.append(source[start:end])
        start = source.find("<svg", end)
    return tags


def _frontend_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for pattern in ("*.tsx", "*.ts"):
        for path in (_FRONTEND / "src").rglob(pattern):
            sources[path.relative_to(_FRONTEND).as_posix()] = path.read_text(encoding="utf-8")
    return sources


class TestTheDonutChart:
    def test_the_named_chart_carries_an_explicit_image_role(self) -> None:
        """The A11Y-11 finding, pinned. `SvgDonut` labels its chart, so the
        label has to sit on an element that exposes it."""
        source = (_FRONTEND / "src" / "components" / "SvgDonut.tsx").read_text(encoding="utf-8")

        named = [tag for tag in _svg_opening_tags(source) if "aria-label" in tag]
        assert any('aria-label="Donut chart"' in tag for tag in named), (
            "the donut chart svg is expected to carry the audited accessible name"
        )
        for tag in named:
            assert _ROLE_IMG.search(tag), f"named svg without role=img: {tag!r}"


class TestEveryNamedSvgInTheFrontend:
    def test_an_accessible_name_always_sits_on_an_explicit_image_role(self) -> None:
        """The invariant the fix establishes: anywhere in `frontend/src` an
        `<svg>` carries an `aria-label`, the same opening tag declares
        `role="img"` — otherwise the name is advisory, not exposed."""
        offenders = [
            f"{rel}: {tag[:80]!r}"
            for rel, source in _frontend_sources().items()
            for tag in _svg_opening_tags(source)
            if "aria-label" in tag and not _ROLE_IMG.search(tag)
        ]

        assert offenders == []
