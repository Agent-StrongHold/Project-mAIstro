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
            external_urls.update(find_external_urls(node.value, url_allowlist))

    return ScanReport(
        passed=not blocking,
        blocking_flags=tuple(blocking),
        external_urls=tuple(sorted(external_urls)),
    )
