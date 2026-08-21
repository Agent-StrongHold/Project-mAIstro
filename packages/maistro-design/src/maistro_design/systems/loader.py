"""DesignSystemLoader — load a DesignSystem from a dict, DESIGN.md, or tokens.css."""

from __future__ import annotations

from typing import Any

from maistro_design.trust import TrustTier
from maistro_design.types import ColorToken, DesignSystem, SpacingToken, TypographyToken


class DesignSystemLoader:
    """Factory for constructing DesignSystem instances from various source formats."""

    @staticmethod
    def from_dict(
        manifest: dict[str, Any],
        *,
        trust_tier: TrustTier = TrustTier.T2,
    ) -> DesignSystem:
        """Build a DesignSystem from a manifest dict (open-design manifest.json shape).

        Minimum required keys: slug, name, description.
        """
        colors = [
            ColorToken(
                name=c["name"],
                value=c["value"],
                group=c.get("group", "brand"),
            )
            for c in manifest.get("colors", [])
        ]
        typography = [
            TypographyToken(
                name=t["name"],
                family=t["family"],
                size=t.get("size", "16px"),
                weight=t.get("weight", "400"),
                line_height=t.get("line_height"),
                letter_spacing=t.get("letter_spacing"),
            )
            for t in manifest.get("typography", [])
        ]
        spacing = [
            SpacingToken(name=s["name"], value=s["value"]) for s in manifest.get("spacing", [])
        ]
        return DesignSystem(
            slug=manifest["slug"],
            name=manifest["name"],
            description=manifest.get("description", ""),
            colors=colors,
            typography=typography,
            spacing=spacing,
            tokens_css=manifest.get("tokens_css", ""),
            components=manifest.get("components", []),
            metadata={
                k: v
                for k, v in manifest.items()
                if k
                not in (
                    "slug",
                    "name",
                    "description",
                    "colors",
                    "typography",
                    "spacing",
                    "tokens_css",
                    "components",
                )
            },
            trust_tier=trust_tier,
        )

    @staticmethod
    def from_markdown(
        text: str,
        *,
        trust_tier: TrustTier = TrustTier.T2,
    ) -> DesignSystem:
        """Build a DesignSystem from a DESIGN.md string with optional YAML front-matter.

        Front-matter fields: slug, name, description.
        The full text is preserved in design_md.
        """
        import re

        slug = ""
        name = ""
        description = ""

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            for line in fm_text.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key == "slug":
                        slug = val
                    elif key == "name":
                        name = val
                    elif key == "description":
                        description = val

        if not slug:
            slug = "unknown"
        if not name:
            name = slug

        return DesignSystem(
            slug=slug,
            name=name,
            description=description,
            design_md=text,
            trust_tier=trust_tier,
        )
