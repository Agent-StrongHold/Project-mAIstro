"""Shared content-scanning primitives for design-system imports and generated outputs.

Detects script/eval injection, prompt-injection phrasing, active markup/CSS network
primitives, base64 blobs, and Unicode steganography. `systems.importer` uses these
for input-side (vendored design-system)
scanning; `scan_design_output` below applies the same primitives output-side, since
generated HTML/SVG/JS/CSS carries the session's contaminated trust tier (ADR-062326-702b).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from maistro.security.normalize import normalize_for_detection
from maistro.security.warden.patterns import ACTIVE_MARKUP_PATTERNS

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
_CSS_URL_RE = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_CSS_IMPORT_RE = re.compile(
    r"@import\b\s*(?:url\s*\(\s*(['\"]?)(.*?)\1\s*\)|(['\"])(.*?)\3)",
    re.IGNORECASE,
)

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

    `blocking_flags` covers script/eval injection, prompt-injection phrasing, active
    markup/CSS network primitives, base64 blobs, Unicode steganography, and banish-list
    hits — any of these
    means `passed=False`. `external_urls` is informational only and never blocks.
    """

    passed: bool
    blocking_flags: tuple[str, ...] = ()
    external_urls: tuple[str, ...] = ()


def _reviewed_url_parts(url: str) -> tuple[str, str, int, str] | None:
    """Parse a URL into the authority fields used by the allowlist."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in {"http", "https"}
        or parts.username is not None
        or parts.password is not None
        or parts.hostname is None
    ):
        return None
    effective_port = port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, effective_port, parts.path


def _is_allowlisted_url(target: str, url_allowlist: tuple[str, ...]) -> bool:
    """Match reviewed URL authorities, not attacker-controlled string prefixes."""
    target_parts = _reviewed_url_parts(target)
    if target_parts is None:
        return False

    for allowed in url_allowlist:
        allowed_parts = _reviewed_url_parts(allowed)
        if allowed_parts is None or target_parts[:3] != allowed_parts[:3]:
            continue
        allowed_path = allowed_parts[3]
        if allowed_path and not (
            target_parts[3] == allowed_path
            or target_parts[3].startswith(allowed_path.rstrip("/") + "/")
        ):
            continue
        return True
    return False


def _css_network_or_code_is_blocking(content: str, url_allowlist: tuple[str, ...]) -> bool:
    """Allow only reviewed documentation/font URLs inside CSS primitives."""
    normalized = normalize_for_detection(content)
    for match in _CSS_URL_RE.finditer(normalized):
        target = re.sub(r"\s+", "", match.group(2)).strip()
        if target.startswith("#"):
            continue
        if not _is_allowlisted_url(target, url_allowlist):
            return True

    for match in _CSS_IMPORT_RE.finditer(normalized):
        target = match.group(2) or match.group(4) or ""
        target = re.sub(r"\s+", "", target).strip()
        if not _is_allowlisted_url(target, url_allowlist):
            return True

    # These primitives can execute code or trigger a request without a URL
    # that the allowlist can meaningfully constrain.
    return bool(
        re.search(
            r"(?:image-set\s*\(|cross-fade\s*\(|element\s*\(|"
            r"paint\s*\(|expression\s*\(|(?:-moz-binding|behavior)\s*:|"
            r"(?:javascript|vbscript)\s*:)",
            normalized,
            re.IGNORECASE,
        )
    )


def _scan_active_markup_patterns(content: str, url_allowlist: tuple[str, ...]) -> list[str]:
    findings: list[str] = []
    normalized = normalize_for_detection(content)
    for pattern, description in ACTIVE_MARKUP_PATTERNS:
        if description == "CSS network/code primitive":
            matched = bool(pattern.search(normalized)) and _css_network_or_code_is_blocking(
                normalized, url_allowlist
            )
        else:
            matched = bool(pattern.search(normalized))
        if matched:
            findings.append(description)
    return findings


def scan_blocking_patterns(
    label: str,
    content: str,
    banish_list: InMemoryTrustBanishList | None,
    *,
    url_allowlist: tuple[str, ...] = DEFAULT_URL_ALLOWLIST,
) -> list[str]:
    """Scan one named piece of text content for the shared blocking vocabulary."""
    blocking: list[str] = []
    if banish_list is not None and banish_list.is_banned(content):
        blocking.append(f"{label}: matches banish-list pattern")

    normalized = normalize_for_detection(content)

    for pattern in _SCRIPT_PATTERNS:
        if pattern.search(normalized):
            blocking.append(f"{label}: matched script pattern {pattern.pattern!r}")

    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(normalized):
            blocking.append(f"{label}: matched prompt-injection pattern {pattern.pattern!r}")

    blocking.extend(
        f"{label}: matched {description}"
        for description in _scan_active_markup_patterns(content, url_allowlist)
    )

    for match in _BASE64_RE.finditer(normalized):
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
        if not _is_allowlisted_url(url, url_allowlist):
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
            blocking.extend(
                scan_blocking_patterns(
                    address,
                    node.value,
                    banish_list,
                    url_allowlist=url_allowlist,
                )
            )
            external_urls.update(find_external_urls(node.value, url_allowlist))

    return ScanReport(
        passed=not blocking,
        blocking_flags=tuple(blocking),
        external_urls=tuple(sorted(external_urls)),
    )
