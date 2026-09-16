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
    def test_root_declares_the_actor_quartet_faces_undo_outcomes_and_floor(self, tokens_css):
        declared = _declared(_root_block(tokens_css))
        for name in ACTOR_TOKENS + FACE_TOKENS + UNDO_TOKENS:
            assert name in declared, name
        assert re.search(r"--text-floor:\s*12px", tokens_css)
        assert re.search(r"--text-xs:\s*12px", tokens_css)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_no_type_size_token_is_under_the_floor(self, tokens_css):
        sizes = [int(px) for px in re.findall(r"--text-[a-z0-9-]+:\s*(\d+)px", tokens_css)]
        assert sizes and min(sizes) >= 12

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
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
    def test_the_dark_scheme_keeps_the_quartet_but_may_change_its_lightness(self, tokens_css):
        dark = re.search(r'^:root\[data-scheme="dark"\] \{(.*?)^\}', tokens_css, re.S | re.M)
        assert dark is not None
        rebound = _declared(dark.group(1))
        assert set(ACTOR_TOKENS) <= rebound
        assert "--text-floor" not in rebound and "--focus-ring" not in rebound

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
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
    def test_previews_carry_no_script_and_reference_only_allowed_hosts(self):
        for page in (WORKSPACE / "components.html", WORKSPACE / "preview" / "home.html"):
            text = page.read_text(encoding="utf-8")
            assert "<script" not in text.lower(), page.name
            for url in re.findall(r"https?://[^\s\"'<>)]+", text):
                assert url.startswith(
                    ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
                ), url
