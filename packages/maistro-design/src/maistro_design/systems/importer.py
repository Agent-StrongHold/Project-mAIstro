"""Importer for Open Design (nexu-io/open-design) design-systems content.

Bridges Open Design's `manifest.json` (schema `od-design-system-project/v1`) +
`DESIGN.md` + `tokens.css` + `design-tokens.json` into a `DesignSystem` instance,
behind a repeatable content security scan.

Two import paths:

- `load_bundled(registry)` — registers the small, install-time "Tier-1" set
  (`BUNDLED_SLUGS`) shipped in `systems/bundled/` at `TrustTier.T1`
  (verified/audited third-party).
- `import_from_catalog(slug, registry)` — one-click import of any system from the
  pre-scanned "Tier-2" catalog shipped in `systems/catalog/`, registered at
  `TrustTier.T2` (community/unaudited) after re-running the scan.

Both tiers are sourced from Open Design's Apache-2.0-licensed `design-systems/`
corpus; see `THIRD_PARTY_NOTICES.md` for provenance and licensing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maistro_design.scan import (
    DEFAULT_URL_ALLOWLIST,
    ScanReport,
    find_external_urls,
    scan_blocking_patterns,
)
from maistro_design.trust import InMemoryTrustBanishList, TrustTier
from maistro_design.types import (
    ColorToken,
    DesignSystem,
    DesignSystemNotFoundError,
    SpacingToken,
    TrustBannedError,
)

if TYPE_CHECKING:
    from maistro_design.protocols import DesignSystemRegistry

_PACKAGE_ROOT = Path(__file__).resolve().parent
BUNDLED_ROOT = _PACKAGE_ROOT / "bundled"
CATALOG_ROOT = _PACKAGE_ROOT / "catalog"
CATALOG_INDEX = CATALOG_ROOT / "catalog.json"

# The four files that carry meaning for prompt-stack assembly and token export.
ESSENTIAL_FILES = ("manifest.json", "DESIGN.md", "tokens.css", "design-tokens.json")

# Install-time "Tier-1" set, registered automatically by load_bundled().
BUNDLED_SLUGS = ("default", "shadcn", "apple", "material", "editorial", "enterprise")

# Where a registered DesignSystem came from, recorded in `metadata["origin"]`.
#
# `trust_tier` is close to this but is not it: T2 is both "imported from the
# Tier-2 catalog" and "handed to us by a caller", and an API that reports the
# catalogue as the source of a system nobody vendored is the same class of
# claim #293 was about. So the loader that knows says so, and anything built
# through `import_open_design_system` directly is EXTERNAL until it says
# otherwise.
ORIGIN_BUNDLED = "bundled"
ORIGIN_CATALOG = "catalog"
ORIGIN_EXTERNAL = "external"


# ─── Scan ──────────────────────────────────────────────────────────────────
# Pattern primitives + ScanReport live in maistro_design.scan (shared with output-side
# scanning in DesignEngine.generate(), per ADR-062326-702b).


def scan_design_system_content(
    files: dict[str, str],
    *,
    banish_list: InMemoryTrustBanishList | None = None,
    url_allowlist: tuple[str, ...] = DEFAULT_URL_ALLOWLIST,
) -> ScanReport:
    """Scan a design system's source files for injection and exfiltration risks.

    `files` maps filenames (e.g. "DESIGN.md") to their text content. Returns a
    `ScanReport`; `passed=False` means the content must not be imported without
    admin review.
    """
    blocking: list[str] = []
    external_urls: set[str] = set()

    for filename, content in files.items():
        blocking.extend(scan_blocking_patterns(filename, content, banish_list))
        external_urls.update(find_external_urls(content, url_allowlist))

    return ScanReport(
        passed=not blocking,
        blocking_flags=tuple(blocking),
        external_urls=tuple(sorted(external_urls)),
    )


# ─── manifest.json + DESIGN.md + tokens.css + design-tokens.json → DesignSystem ──


def import_open_design_system(
    manifest: dict[str, Any],
    *,
    design_md: str = "",
    tokens_css: str = "",
    design_tokens: dict[str, Any] | None = None,
    trust_tier: TrustTier = TrustTier.T2,
    origin: str = ORIGIN_EXTERNAL,
) -> DesignSystem:
    """Build a `DesignSystem` from Open Design's bundled-package shape.

    `manifest` is the parsed `manifest.json` (schema `od-design-system-project/v1`,
    keyed by `id` rather than `slug`, with nested `files`/`craft`/`preview`/
    `sourceFiles`). `design_tokens` is the parsed `design-tokens.json`
    (`od-design-tokens/v1`); its flat `tokens` array is used to populate
    `colors` (type == "color") and `spacing` (dimension tokens named `--space-*`).
    """
    colors: list[ColorToken] = []
    spacing: list[SpacingToken] = []
    for token in (design_tokens or {}).get("tokens", []):
        name = token.get("name", "")
        value = token.get("value", "")
        token_type = token.get("type")
        if token_type == "color":
            colors.append(ColorToken(name=name, value=value, group="open-design"))
        elif token_type == "dimension" and name.startswith("--space-"):
            spacing.append(SpacingToken(name=name, value=value))

    slug = manifest.get("id") or manifest.get("slug") or "unknown"
    metadata = {
        "category": manifest.get("category", ""),
        "source": manifest.get("source", {}),
        "open_design_id": slug,
        "license": "Apache-2.0",
        "origin": origin,
    }

    return DesignSystem(
        slug=slug,
        name=manifest.get("name", slug),
        description=manifest.get("description", ""),
        colors=colors,
        spacing=spacing,
        tokens_css=tokens_css,
        design_md=design_md,
        metadata=metadata,
        trust_tier=trust_tier,
    )


# ─── Loading from disk ────────────────────────────────────────────────────────


def _read_system_files(
    system_dir: Path,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any] | None]:
    manifest = json.loads((system_dir / "manifest.json").read_text(encoding="utf-8"))
    design_md = (system_dir / "DESIGN.md").read_text(encoding="utf-8")
    tokens_css = (system_dir / "tokens.css").read_text(encoding="utf-8")
    design_tokens_path = system_dir / "design-tokens.json"
    design_tokens = (
        json.loads(design_tokens_path.read_text(encoding="utf-8"))
        if design_tokens_path.exists()
        else None
    )
    files = {
        "manifest.json": json.dumps(manifest),
        "DESIGN.md": design_md,
        "tokens.css": tokens_css,
    }
    if design_tokens is not None:
        files["design-tokens.json"] = json.dumps(design_tokens)
    return manifest, files, design_tokens


def load_bundled(registry: DesignSystemRegistry) -> None:
    """Register the Tier-1 install-time design systems (`BUNDLED_SLUGS`) at T1."""
    for slug in BUNDLED_SLUGS:
        system_dir = BUNDLED_ROOT / slug
        manifest, files, design_tokens = _read_system_files(system_dir)
        system = import_open_design_system(
            manifest,
            design_md=files["DESIGN.md"],
            tokens_css=files["tokens.css"],
            design_tokens=design_tokens,
            trust_tier=TrustTier.T1,
            origin=ORIGIN_BUNDLED,
        )
        registry.register(system)


def load_catalog() -> list[dict[str, Any]]:
    """Return the full Tier-2 catalog index (`catalog.json`)."""
    return json.loads(CATALOG_INDEX.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def import_from_catalog(
    slug: str,
    registry: DesignSystemRegistry,
    *,
    trust_tier: TrustTier = TrustTier.T2,
    banish_list: InMemoryTrustBanishList | None = None,
) -> DesignSystem:
    """One-click import of a pre-scanned Tier-2 design system into `registry`.

    Re-runs `scan_design_system_content` at import time (defense-in-depth — the
    catalog's `scan_status` reflects the scan at vendoring time, not now) and
    raises `TrustBannedError` if it no longer passes.
    """
    system_dir = CATALOG_ROOT / slug
    if not system_dir.is_dir():
        msg = f"Design system '{slug}' not found in the Open Design catalog"
        raise DesignSystemNotFoundError(msg)

    manifest, files, design_tokens = _read_system_files(system_dir)
    report = scan_design_system_content(files, banish_list=banish_list)
    if not report.passed:
        msg = f"Design system '{slug}' failed the import scan: {report.blocking_flags}"
        raise TrustBannedError(msg)

    system = import_open_design_system(
        manifest,
        design_md=files["DESIGN.md"],
        tokens_css=files["tokens.css"],
        design_tokens=design_tokens,
        trust_tier=trust_tier,
        origin=ORIGIN_CATALOG,
    )
    registry.register(system)
    return system
