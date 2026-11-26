"""The `workspace` design system is first-party, bundled at T1, and carries the
Workspace surface's grammar in its tokens (ADR-091626-ba4f).

The other bundled systems are vendored brand inspirations; this one is the
product's own. What makes it the product's own is checkable: the four actor
colours exist and are the same in every persona, the four state faces exist,
the type floor is 12px, and a persona template rebinds only what DESIGN.md
says a persona may rebind.
"""

from __future__ import annotations

import json
import re

import pytest

from maistro_design.systems.importer import (
    BUNDLED_ROOT,
    BUNDLED_SLUGS,
    ORIGIN_BUNDLED,
    load_bundled,
    load_catalog,
    scan_design_system_content,
)
from maistro_design.systems.registry import InMemoryDesignSystemRegistry
from maistro_design.trust import TrustTier

WORKSPACE = BUNDLED_ROOT / "workspace"
ACTOR_TOKENS = ("--actor-human", "--actor-agent", "--actor-gate", "--actor-system")
FACE_TOKENS = ("--face-loading", "--face-empty-bg", "--face-error-bg", "--face-denied-bg")
UNDO_TOKENS = ("--undo-ok-bg", "--undo-partial-bg", "--undo-logged-fg")
PERSONA_MAY_SET = {"--bg", "--surface", "--bloom", "--accent", "--accent-on"}


def _root_block(css: str) -> str:
    return re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)


def _declared(block: str) -> set[str]:
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))


@pytest.fixture(scope="module")
def tokens_css() -> str:
    return (WORKSPACE / "tokens.css").read_text(encoding="utf-8")


class TestItIsBundledLikeTheOthers:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    @pytest.mark.ac("ADR-091626-ba4f/AC-1")
    def test_workspace_is_a_bundled_slug_registered_at_t1(self):
        assert "workspace" in BUNDLED_SLUGS
        registry = InMemoryDesignSystemRegistry()
        load_bundled(registry)
        system = registry.get("workspace")
        assert system is not None
        assert system.trust_tier == TrustTier.T1
        assert system.metadata["origin"] == ORIGIN_BUNDLED
        assert system.design_md and system.tokens_css
        assert len(system.colors) > 20

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-2")
    def test_the_catalog_index_says_it_is_first_party(self):
        (entry,) = [e for e in load_catalog() if e["slug"] == "workspace"]
        assert entry["tier"] == ORIGIN_BUNDLED
        assert entry["trust_tier"] == "t1"
        assert entry["license"] == "Apache-2.0"
        assert entry["source"]["repo"] == "Agent-StrongHold/Project-mAIstro"
        manifest = json.loads((WORKSPACE / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["source"]["type"] == "first-party"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-3")
    def test_its_essential_files_pass_the_import_scan(self):
        files = {
            name: (WORKSPACE / name).read_text(encoding="utf-8")
            for name in ("manifest.json", "DESIGN.md", "tokens.css", "design-tokens.json")
        }
        report = scan_design_system_content(files)
        assert report.passed, report.blocking_flags
        assert report.external_urls == ()


class TestTheGrammarIsInTheTokens:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-4")
    def test_root_declares_the_actor_quartet_faces_undo_outcomes_and_floor(self, tokens_css):
        declared = _declared(_root_block(tokens_css))
        for name in ACTOR_TOKENS + FACE_TOKENS + UNDO_TOKENS:
            assert name in declared, name
        assert re.search(r"--text-floor:\s*12px", tokens_css)
        assert re.search(r"--text-xs:\s*12px", tokens_css)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-4")
    def test_no_type_size_token_is_under_the_floor(self, tokens_css):
        sizes = [int(px) for px in re.findall(r"--text-[a-z0-9-]+:\s*(\d+)px", tokens_css)]
        assert sizes and min(sizes) >= 12

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-5")
    def test_persona_templates_rebind_only_what_a_persona_may(self, tokens_css):
        """Slate and studio are the reference for a user-authored theme: if they
        touched an actor colour or a face, a custom theme could too."""
        blocks = re.findall(
            r'^:root\[data-theme="(slate|studio)"\](?:\[data-scheme="dark"\])? \{(.*?)^\}',
            tokens_css,
            re.S | re.M,
        )
        assert len(blocks) == 4
        for name, block in blocks:
            rebound = _declared(block)
            assert rebound, name
            assert rebound <= PERSONA_MAY_SET, (name, rebound - PERSONA_MAY_SET)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-5")
    def test_the_dark_scheme_keeps_the_quartet_but_may_change_its_lightness(self, tokens_css):
        dark = re.search(r'^:root\[data-scheme="dark"\] \{(.*?)^\}', tokens_css, re.S | re.M)
        assert dark is not None
        rebound = _declared(dark.group(1))
        assert set(ACTOR_TOKENS) <= rebound
        assert "--text-floor" not in rebound and "--focus-ring" not in rebound

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-6")
    def test_design_tokens_json_mirrors_the_root_block(self, tokens_css):
        exported = {
            t["name"]
            for t in json.loads((WORKSPACE / "design-tokens.json").read_text(encoding="utf-8"))[
                "tokens"
            ]
        }
        assert exported == _declared(_root_block(tokens_css))


class TestThePreviewsAreStatic:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-6")
    def test_previews_carry_no_script_and_reference_only_allowed_hosts(self):
        for page in (WORKSPACE / "components.html", WORKSPACE / "preview" / "home.html"):
            text = page.read_text(encoding="utf-8")
            assert "<script" not in text.lower(), page.name
            for url in re.findall(r"https?://[^\s\"'<>)]+", text):
                assert url.startswith(
                    ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
                ), url


# ─── the contrast claims DESIGN.md makes, computed rather than asserted in prose ──


def _hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(_hex_rgb(a)), _luminance(_hex_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _tint(fg: str, over: str, amount: float = 0.16) -> str:
    """`color-mix(in srgb, fg 16%, transparent)` composited over an opaque surface."""
    f, o = _hex_rgb(fg), _hex_rgb(over)
    mixed = tuple(f[i] * amount + o[i] * (1 - amount) for i in range(3))
    return "#" + "".join(f"{round(v * 255):02x}" for v in mixed)


def _hex_tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", block))


def _blocks(tokens_css: str) -> dict[str, dict[str, str]]:
    """Every selector block's hex tokens, keyed by selector; `:root` first."""
    out: dict[str, dict[str, str]] = {}
    for selector, body in re.findall(r"^(:root[^{\n]*) \{(.*?)^\}", tokens_css, re.S | re.M):
        out[selector.strip()] = _hex_tokens(body)
    return out


def _resolved_palettes(tokens_css: str) -> dict[str, dict[str, str]]:
    """The effective hex palette for each persona and scheme, resolved the way the
    cascade resolves it: root, then the scheme block, then the persona block(s)."""
    blocks = _blocks(tokens_css)
    root = blocks[":root"]
    dark = blocks[':root[data-scheme="dark"]']
    palettes: dict[str, dict[str, str]] = {}
    for persona in ("greenhouse", "slate", "studio"):
        light = {**root, **blocks.get(f':root[data-theme="{persona}"]', {})}
        dark_p = {
            **root,
            **dark,
            **blocks.get(f':root[data-theme="{persona}"][data-scheme="dark"]', {}),
        }
        palettes[f"{persona}/light"] = light
        palettes[f"{persona}/dark"] = dark_p
    return palettes


class TestTheContrastClaimsHold:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-4")
    def test_text_on_field_and_surface_clears_the_threshold_in_every_persona(self, tokens_css):
        """Ink, secondary text and the 12px machine register against the field
        and the opaque panel fallback: 4.5:1 in light, 6:1 in dark."""
        for name, p in _resolved_palettes(tokens_css).items():
            floor = 6.0 if name.endswith("/dark") else 4.5
            for text in ("--fg", "--fg-2", "--muted", "--meta"):
                for ground in ("--bg", "--surface"):
                    ratio = _contrast(p[text], p[ground])
                    assert ratio >= floor, (name, text, ground, round(ratio, 2))

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-4")
    def test_badge_text_on_its_own_tint_clears_the_threshold_in_every_persona(self, tokens_css):
        """A badge is 12px text on a 16% tint of its own colour. The tint is
        translucent, so it is measured composited over the lightest thing it can
        sit on (the surface) and over the field: 5:1 in light, 5.5:1 in dark."""
        for name, p in _resolved_palettes(tokens_css).items():
            floor = 5.5 if name.endswith("/dark") else 5.0
            for colour in (*ACTOR_TOKENS, "--warn", "--success", "--danger"):
                for ground in ("--surface", "--bg"):
                    ratio = _contrast(p[colour], _tint(p[colour], p[ground]))
                    assert ratio >= floor, (name, colour, ground, round(ratio, 2))

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.ac("ADR-091626-ba4f/AC-5")
    def test_the_persona_accent_clears_the_gate_it_asks_custom_themes_to_clear(self, tokens_css):
        """DESIGN.md rejects a custom theme under 4.5:1 for accent-on over accent
        and accent over the field. The shipped templates pass their own gate."""
        for name, p in _resolved_palettes(tokens_css).items():
            assert _contrast(p["--accent-on"], p["--accent"]) >= 4.5, name
            assert _contrast(p["--accent"], p["--bg"]) >= 4.5, name


class TestThePersonaContractReachesConsumers:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("integration")
    @pytest.mark.ac("ADR-091626-ba4f/AC-2")
    def test_the_manifests_personas_block_survives_the_bundled_load(self):
        """The persona editor reads templates, schemes and the customizable /
        fixed token sets from the loaded system, not from the file on disk."""
        registry = InMemoryDesignSystemRegistry()
        load_bundled(registry)
        personas = registry.get("workspace").metadata["personas"]
        manifest = json.loads((WORKSPACE / "manifest.json").read_text(encoding="utf-8"))
        assert personas == manifest["personas"]
        assert personas["default"] in personas["templates"]
        assert set(personas["customizable"]) & set(personas["fixed"]) == set()
        # A vendored brand system advertises no persona contract, and says so
        # by absence rather than by an empty stand-in.
        assert "personas" not in registry.get("default").metadata

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    def test_the_stale_age_threshold_exports_as_a_duration(self):
        tokens = json.loads((WORKSPACE / "design-tokens.json").read_text(encoding="utf-8"))[
            "tokens"
        ]
        (token,) = [t for t in tokens if t["name"] == "--age-stale-after"]
        assert token["type"] == "duration"
        assert re.fullmatch(r"\d+(ms|s)", token["value"])
