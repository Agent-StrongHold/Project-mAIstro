"""Shared content-scanning primitives for design-system imports and generated outputs.

Detects script/eval injection, prompt-injection phrasing, base64 blobs, and Unicode
steganography. `systems.importer` uses these for input-side (vendored design-system)
scanning; `scan_design_output` below applies the same primitives output-side, since
generated HTML/SVG/JS/CSS carries the session's contaminated trust tier (ADR-062326-702b).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro_design.trust import InMemoryTrustBanishList
    from maistro_design.types import DesignOutput

_SCRIPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"<iframe\b", re.IGNORECASE),
    re.compile(r"<object\b", re.IGNORECASE),
    re.compile(r"<embed\b", re.IGNORECASE),
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bFunction\s*\(", re.IGNORECASE),
    re.compile(r"\bXMLHttpRequest\b"),
    re.compile(r"\bnew\s+WebSocket\s*\("),
    re.compile(r"\bfetch\s*\("),
    re.compile(r"javascript:", re.IGNORECASE),
)

_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+|any\s+)?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+|your\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+mode\b", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+)?(DAN|jailbroken)", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?system\s+prompt", re.IGNORECASE),
)

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")

# Keep these reason names in sync with the frontend visual-artifact boundary.
# This is deliberately conservative: trust recommendations must not upgrade
# content that the browser renderer will remove or neutralize.
VISUAL_ARTIFACT_BLOCK_REASONS: tuple[str, ...] = (
    "active-element",
    "event-handler",
    "dangerous-url",
    "unsupported-attribute",
    "unsupported-css-property",
    "css-network-or-code",
)

# Allowed tag names (HTML and SVG) as per frontend visualArtifactRenderer.tsx
_HTML_TAGS = {
    "article",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "i",
    "li",
    "main",
    "ol",
    "p",
    "pre",
    "section",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_SVG_TAGS = {
    "circle",
    "ellipse",
    "g",
    "line",
    "lineargradient",
    "path",
    "polygon",
    "polyline",
    "radialgradient",
    "rect",
    "stop",
    "svg",
    "text",
    "tspan",
}
_ALLOWED_TAGS = _HTML_TAGS | _SVG_TAGS

# Allowed attribute names (HTML and SVG) as per frontend visualArtifactRenderer.tsx
_HTML_ATTRIBUTES = {
    "aria-hidden",
    "aria-label",
    "dir",
    "role",
    "style",
    "title",
}
_SVG_ATTRIBUTES = {
    "aria-hidden",
    "aria-label",
    "cx",
    "cy",
    "d",
    "dir",
    "fill",
    "fill-opacity",
    "font-size",
    "font-weight",
    "gradientunits",
    "height",
    "offset",
    "opacity",
    "points",
    "preserveaspectratio",
    "r",
    "role",
    "rx",
    "ry",
    "spreadmethod",
    "stop-color",
    "stop-opacity",
    "stroke",
    "stroke-dasharray",
    "stroke-dashoffset",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-opacity",
    "stroke-width",
    "style",
    "text-anchor",
    "text-transform",
    "title",
    "transform",
    "transform-origin",
    "viewbox",
    "width",
    "x",
    "x1",
    "x2",
    "y",
    "y1",
    "y2",
}
# Allowed CSS properties as per frontend visualArtifactRenderer.tsx
_STYLE_PROPERTIES = {
    "align-content",
    "align-items",
    "align-self",
    "aspect-ratio",
    "background",
    "background-color",
    "background-image",
    "background-position",
    "background-repeat",
    "background-size",
    "border",
    "border-bottom",
    "border-bottom-color",
    "border-bottom-left-radius",
    "border-bottom-right-radius",
    "border-bottom-style",
    "border-bottom-width",
    "border-color",
    "border-left",
    "border-left-color",
    "border-left-style",
    "border-left-width",
    "border-radius",
    "border-right",
    "border-right-color",
    "border-right-style",
    "border-right-width",
    "border-style",
    "border-top",
    "border-top-color",
    "border-top-left-radius",
    "border-top-right-radius",
    "border-top-style",
    "border-top-width",
    "border-width",
    "bottom",
    "box-sizing",
    "color",
    "column-gap",
    "display",
    "flex",
    "flex-basis",
    "flex-direction",
    "flex-grow",
    "flex-shrink",
    "flex-wrap",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "gap",
    "height",
    "justify-content",
    "left",
    "letter-spacing",
    "line-height",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "min-height",
    "min-width",
    "object-fit",
    "opacity",
    "overflow",
    "overflow-x",
    "overflow-y",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "position",
    "right",
    "row-gap",
    "text-align",
    "text-decoration",
    "text-overflow",
    "text-transform",
    "top",
    "transform",
    "transform-origin",
    "vertical-align",
    "white-space",
    "width",
    "word-break",
    "z-index",
    "-webkit-background-clip",
    "-webkit-text-fill-color",
}

# Regular expressions for detecting network/code in CSS values and attribute values
_NETWORK_OR_CODE_CSS = re.compile(
    r"(?:url\s*\(|image-set\s*\(|cross-fade\s*\(|element\s*\(|paint\s*\(|expression\s*\(|javascript\s*:|vbscript\s*:|data\s*:|@import|behavior\s*:|-moz-binding|var\s*\(|env\s*\()",
    re.IGNORECASE,
)
_NETWORK_OR_CODE_ATTRIBUTE = re.compile(
    r"(?:url\s*\(|javascript\s*:|vbscript\s*:|data\s*:|https?\s*:|\/\/)",
    re.IGNORECASE,
)


class _VisualArtifactScanner(HTMLParser):
    """Parse HTML/SVG and collect reasons for blocking based on allowlists."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.reasons: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag)
        for attr, value in attrs:
            self._check_attribute(tag, attr, value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag)
        for attr, value in attrs:
            self._check_attribute(tag, attr, value)

    def _check_tag(self, tag: str) -> None:
        if tag.lower() not in _ALLOWED_TAGS:
            self.reasons.add("active-element")

    def _check_attribute(self, tag: str, attr: str, value: str | None) -> None:
        attr_lower = attr.lower()
        # A bare attribute (`<div style>`) has a null value; the DOM models the
        # same thing as the empty string.
        value = value or ""
        attr_lower = attr.lower()
        # Event handler attributes
        if attr_lower.startswith("on"):
            self.reasons.add("event-handler")
            return
        # Attributes with colon (including XML namespaces like xlink:href) are unsupported
        if ":" in attr:
            self.reasons.add("unsupported-attribute")
            self._check_value_for_dangerous_url(value)
            return
        # Namespace parity with the frontend renderer: SVG elements accept the
        # SVG attribute set, everything else the HTML set. Inside an allowed
        # SVG subtree every tag is an SVG tag, so the tag name selects the same
        # set the browser's namespaceURI check would.
        allowed = _SVG_ATTRIBUTES if tag.lower() in _SVG_TAGS else _HTML_ATTRIBUTES
        if attr_lower not in allowed:
            self.reasons.add("unsupported-attribute")
            self._check_value_for_dangerous_url(value)
            return
        # Style attribute: parse CSS
        if attr_lower == "style":
            self._check_style(value)
            return
        # Other attributes: check for dangerous URLs
        self._check_value_for_dangerous_url(value)

    def _check_value_for_dangerous_url(self, value: str) -> None:
        # The renderer strips disallowed attributes without inspecting their
        # values, but the pre-scan must never see less than the corpus does: a
        # `data:`/`javascript:` scheme inside a stripped attribute is hostile
        # content the boundary removed, so it still blocks a trust upgrade.
        if _NETWORK_OR_CODE_ATTRIBUTE.search(value):
            self.reasons.add("dangerous-url")

    def _check_style(self, style_text: str) -> None:
        # Parse simple CSS: property: value; pairs
        for declaration in style_text.split(";"):
            if not declaration.strip():
                continue
            if ":" not in declaration:
                # Malformed, treat as unsupported
                self.reasons.add("unsupported-css-property")
                continue
            prop, val = declaration.split(":", 1)
            prop = prop.strip().lower()
            val = val.strip()
            # Check if property is allowed
            if prop not in _STYLE_PROPERTIES:
                # Certain properties that can load code or URLs are treated as css-network-or-code
                if "image" in prop or prop == "mask" or prop == "content":
                    self.reasons.add("css-network-or-code")
                else:
                    self.reasons.add("unsupported-css-property")
                continue
            # Check value for network/code patterns
            if _NETWORK_OR_CODE_CSS.search(val):
                self.reasons.add("css-network-or-code")


def scan_visual_artifact_markup(content: str) -> tuple[str, ...]:
    """Return shared blocking reasons for HTML/SVG visual-artifact content.

    Mirrors the frontend's visualArtifactRenderer.scanVisualArtifactMarkup:
    the same tag/attribute/CSS allowlists and the same reason vocabulary
    (VISUAL_ARTIFACT_BLOCK_REASONS), so the trust pre-scan (#817) classifies
    content with the words the browser boundary blocks in. The pre-scan is a
    deliberate conservative superset of the renderer: values inside attributes
    the renderer simply strips are still scanned for dangerous schemes, and an
    unparseable payload fails closed (every reason), so no construct the
    rendering boundary removes can ever be recommended for trust upgrade.
    """
    if not content:
        return ()
    scanner = _VisualArtifactScanner()
    try:
        scanner.feed(content)
        scanner.close()
    except Exception:
        # Fail closed: if the parser cannot vouch for the content, no trust
        # recommendation may call it upgradeable. `html.parser` is tolerant by
        # design, so this path should be unreachable — it exists so a parser
        # regression can never silently reopen the boundary.
        return VISUAL_ARTIFACT_BLOCK_REASONS
    # Deterministic order matching VISUAL_ARTIFACT_BLOCK_REASONS / the frontend
    # vocabulary order, so recorded warden_flags are stable.
    return tuple(reason for reason in VISUAL_ARTIFACT_BLOCK_REASONS if reason in scanner.reasons)


# Documentation/font-CDN links that are expected to appear in design-system prose.

# Documentation/font-CDN links that are expected to appear in design-system prose.
DEFAULT_URL_ALLOWLIST: tuple[str, ...] = (
    "https://fonts.googleapis.com",
    "https://fonts.gstatic.com",
    "https://fonts.google.com",
    "https://developer.mozilla.org",
    "https://www.w3.org",
)


@dataclass(frozen=True)
class ScanReport:
    """Result of a content scan.

    `blocking_flags` covers script/eval injection, prompt-injection phrasing,
    base64 blobs, Unicode steganography, and banish-list hits — any of these
    means `passed=False`. `external_urls` is informational only and never blocks.
    """

    passed: bool
    blocking_flags: tuple[str, ...] = ()
    external_urls: tuple[str, ...] = ()


def scan_blocking_patterns(
    label: str, content: str, banish_list: InMemoryTrustBanishList | None
) -> list[str]:
    """Scan one named piece of text content for blocking patterns. `label` tags findings."""
    blocking: list[str] = []
    if banish_list is not None and banish_list.is_banned(content):
        blocking.append(f"{label}: matches banish-list pattern")

    for pattern in _SCRIPT_PATTERNS:
        if pattern.search(content):
            blocking.append(f"{label}: matched script pattern {pattern.pattern!r}")

    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(content):
            blocking.append(f"{label}: matched prompt-injection pattern {pattern.pattern!r}")

    for match in _BASE64_RE.finditer(content):
        blocking.append(f"{label}: base64 blob ({len(match.group(0))} chars)")

    for offset, ch in enumerate(content):
        category = unicodedata.category(ch)
        if category in ("Cf", "Co") or (category == "Cc" and ch not in "\t\n\r"):
            blocking.append(
                f"{label}: suspicious Unicode {category} U+{ord(ch):04X} at offset {offset}"
            )
            break

    return blocking


def find_external_urls(content: str, url_allowlist: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for url in _URL_RE.findall(content):
        url = url.rstrip("`).,;\"'")
        if not any(url.startswith(prefix) for prefix in url_allowlist):
            found.add(url)
    return found


def scan_design_output(
    output: DesignOutput,
    *,
    banish_list: InMemoryTrustBanishList | None = None,
    url_allowlist: tuple[str, ...] = DEFAULT_URL_ALLOWLIST,
) -> ScanReport:
    """Scan every text leaf in a DesignOutput's artifact tree before it is returned.

    Binary (BLOB) leaves are not pattern-scanned — there is no text to match against;
    binary content safety is the renderer/asset-store boundary's concern.
    """
    blocking: list[str] = []
    external_urls: set[str] = set()

    for address, node in output.root.walk():
        if isinstance(node.value, str):
            blocking.extend(scan_blocking_patterns(address, node.value, banish_list))
            for reason in scan_visual_artifact_markup(node.value):
                blocking.append(f"{address}: visual artifact {reason}")
            external_urls.update(find_external_urls(node.value, url_allowlist))

    return ScanReport(
        passed=not blocking,
        blocking_flags=tuple(blocking),
        external_urls=tuple(sorted(external_urls)),
    )
