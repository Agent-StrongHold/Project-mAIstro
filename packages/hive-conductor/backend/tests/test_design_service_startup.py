"""The Conductor's design service registers the real bundled systems (#293).

`start_design_service` imported `maistro_design.systems.builtins` -- a module
that has never existed in any version of that package -- inside a bare
`except Exception` that substituted a hand-built `DesignSystem(slug="default")`
carrying no tokens at `TrustTier.T0`.

The substitution is what let it survive. An empty registry would have raised
`DesignSystemNotFoundError` on the first generation and been fixed the same
day; a stub answering to a real system's slug produced plausible output from an
empty palette, and the other five bundled systems were absent entirely.

Everything below is asserted through `DesignEngine.generate` -- the seam a
`POST /design/projects` request reaches -- rather than by reading the registry
the service built. Startup succeeded before the fix too, so "it started" is not
evidence of anything; what changed is the prompt the model receives.
"""

from __future__ import annotations

import re

import pytest
from services import design_service

from maistro_design.systems.importer import BUNDLED_SLUGS
from maistro_design.types import DesignSystemNotFoundError, DiscoveryResult

#: A built-in skill with no `compatible_design_systems` restriction, so the
#: system lookup is the only thing that can fail here.
SKILL = "login-flow"
RESPONSES = {"auth_methods": "email and passkey", "brand_tone": "calm"}


@pytest.fixture
async def engine(monkeypatch):
    """The engine `start_design_service` actually builds, with no database.

    The singletons are module globals; monkeypatch restores them so a test
    cannot change what the next one measures.
    """
    monkeypatch.setattr(design_service, "_get_async_session_factory", lambda: None)
    monkeypatch.setattr(design_service, "_engine_singleton", None)
    monkeypatch.setattr(design_service, "_store_singleton", None)
    monkeypatch.setattr(design_service, "_renderer_registry_singleton", None)

    class _Settings:
        open_design_url = None
        open_design_api_key = None

    await design_service.start_design_service(_Settings())
    return design_service.get_design_engine()


async def _prompt(engine, slug: str) -> str:
    project = await engine.generate(DiscoveryResult(SKILL, RESPONSES, design_system_slug=slug))
    return str(project.outputs[0].content)


class TestEveryBundledSystemResolves:
    @pytest.mark.parametrize("slug", BUNDLED_SLUGS)
    async def test_a_generation_against_each_bundled_slug_succeeds(self, engine, slug):
        """Five of these six raised `DesignSystemNotFoundError` from
        `DesignEngine.generate` before the fix, because nothing registered
        them. `default` was the sixth, and worse -- see below."""
        assert await _prompt(engine, slug)

    async def test_an_unknown_slug_still_raises(self, engine):
        """The fix must not have made the engine permissive. Inventing a system
        to answer an unknown slug with is precisely what #293 was, so the error
        for a slug nobody bundles has to survive the change."""
        with pytest.raises(DesignSystemNotFoundError):
            await _prompt(engine, "no-such-design-system")


class TestTheStubIsGone:
    """`default` is the case slug-presence cannot detect: the stub and the real
    system answer to the same name. Only the prompt tells them apart."""

    async def test_the_prompt_carries_the_systems_colour_tokens(self, engine):
        """The stub had none, so a generation against "default" reached the
        model with an empty palette and produced a design in no particular
        colours -- silently, and looking entirely normal.

        Asserted as "several", not as 16: the point is that tokens reach the
        prompt at all, and pinning the count would turn an upstream palette
        tweak into a failure here."""
        assert len(re.findall(r"#[0-9a-fA-F]{6}", await _prompt(engine, "default"))) > 3

    async def test_different_systems_produce_different_prompts(self, engine):
        """The end of the defect, stated as the property that matters: choosing
        a design system changes the design. Under the stub, five of the six
        choices were unavailable and the sixth was empty, so this could not
        have held for any pair."""
        prompts = {slug: await _prompt(engine, slug) for slug in BUNDLED_SLUGS}
        assert len(set(prompts.values())) == len(BUNDLED_SLUGS)


class TestTheImportItself:
    async def test_the_loader_is_the_one_the_rest_of_the_package_uses(self):
        """`maistro_design.nodes` imported `load_bundled` correctly all along,
        so the package had a working entry point the whole time and the
        Conductor was the only caller reaching for a module that was not
        there. Worth pinning: if these two ever diverge again, the Conductor is
        the one that will do it quietly."""
        from maistro_design import nodes
        from maistro_design.systems import importer

        assert nodes.load_bundled is importer.load_bundled

    async def test_a_failure_to_load_is_not_swallowed_into_a_substitute(self, monkeypatch):
        """The behaviour the fix removed. These systems are packaged data, not
        an optional catalog: if they cannot load the install is broken, and
        startup must say so rather than fabricating a product to ship in their
        place."""
        from maistro_design.systems import importer

        def _broken(registry):
            raise RuntimeError("bundled systems are unreadable")

        monkeypatch.setattr(importer, "load_bundled", _broken)
        monkeypatch.setattr(design_service, "_get_async_session_factory", lambda: None)
        monkeypatch.setattr(design_service, "_engine_singleton", None)

        class _Settings:
            open_design_url = None
            open_design_api_key = None

        await design_service.start_design_service(_Settings())
        with pytest.raises(RuntimeError, match="not initialized"):
            design_service.get_design_engine()


class TestTheStatusStartupLeavesBehind:
    """Before #293, a failure to load the design systems was a `logger.warning`
    and nothing else -- visible only to whoever read the container log on the
    right day, while every caller after that point saw a service that looked
    ready. The status is what makes the failure answerable."""

    async def test_a_started_service_reports_ready_with_its_bundled_set(self, engine):
        status = design_service.get_design_status()
        assert status.ready
        assert status.cause is None
        assert set(status.bundled_slugs) == set(BUNDLED_SLUGS)

    async def test_a_failed_start_records_the_cause(self, monkeypatch):
        """Not "ready with a substitute", and not "not ready" with nothing to
        act on: the exception that stopped it, in a form a route can return."""
        from maistro_design.systems import importer

        monkeypatch.setattr(design_service, "_engine_singleton", None)
        monkeypatch.setattr(design_service, "_status", design_service.DesignServiceStatus())
        monkeypatch.setattr(design_service, "_get_async_session_factory", lambda: None)

        def _broken(registry):
            raise FileNotFoundError("systems/bundled/default/manifest.json")

        monkeypatch.setattr(importer, "load_bundled", _broken)

        class _Settings:
            open_design_url = None
            open_design_api_key = None

        await design_service.start_design_service(_Settings())
        status = design_service.get_design_status()
        assert not status.ready
        assert "FileNotFoundError" in (status.cause or "")
        assert "manifest.json" in (status.cause or "")

    async def test_an_unstarted_service_says_so_rather_than_looking_ready(self):
        """The default. `ready` is False until something proves otherwise,
        which is the direction this whole issue was pointed the wrong way."""
        assert not design_service.DesignServiceStatus().ready


class TestTheOptionalCatalog:
    """The Tier-2 half: 144 systems a user imports one at a time, none of them
    registered at startup. Optional, so its absence degrades rather than
    breaks -- but degraded *with a cause*, not as an empty list that reads like
    "nothing to import"."""

    async def test_a_present_catalog_is_reported_available(self, engine):
        status = design_service.get_design_status()
        assert status.catalog_available
        assert status.catalog_cause is None
        assert len(status.catalog_slugs) > 100

    async def test_the_catalog_excludes_the_bundled_tier(self, engine):
        """The index covers both tiers; `import_from_catalog` reads the
        catalogue directory only. Offering the index verbatim would offer six
        systems that cannot be imported from the path implied."""
        status = design_service.get_design_status()
        assert not set(status.catalog_slugs) & set(BUNDLED_SLUGS)

    async def test_an_unreadable_catalog_degrades_with_a_cause(self, monkeypatch):
        """And does not stop the service: the required half loaded."""
        from maistro_design.systems import importer

        monkeypatch.setattr(design_service, "_engine_singleton", None)
        monkeypatch.setattr(design_service, "_status", design_service.DesignServiceStatus())
        monkeypatch.setattr(design_service, "_get_async_session_factory", lambda: None)

        def _broken():
            raise FileNotFoundError("catalog.json")

        monkeypatch.setattr(importer, "load_catalog", _broken)

        class _Settings:
            open_design_url = None
            open_design_api_key = None

        await design_service.start_design_service(_Settings())
        status = design_service.get_design_status()
        assert status.ready
        assert not status.catalog_available
        assert "catalog.json" in (status.catalog_cause or "")
        assert status.catalog_slugs == ()


class TestTheCatalogClaimIsVerified:
    """#413. `_probe_catalog` read `catalog.json` and reported its 144 slugs as
    available. `import_from_catalog` reads `systems/catalog/<slug>/`, not the
    index — so a build carrying the index without the payloads advertised 144
    importable systems and failed every one on click.

    The index is a claim; the files are the fact.
    """

    async def test_the_reported_slugs_all_have_files_installed(self, engine):
        from maistro_design.systems.importer import CATALOG_ROOT

        status = design_service.get_design_status()
        missing = [
            slug
            for slug in status.catalog_slugs
            if not (CATALOG_ROOT / slug / "manifest.json").is_file()
        ]
        assert missing == []

    async def test_an_index_with_no_payloads_is_unavailable_not_available(self, monkeypatch):
        """The state the wheel declaration used to permit. Reporting 144
        available here is the exact "fabricated completeness" #293 was."""
        from maistro_design.systems import importer

        monkeypatch.setattr(
            importer,
            "load_catalog",
            lambda: [{"slug": "ghost", "tier": "catalog"}, {"slug": "phantom", "tier": "catalog"}],
        )
        slugs, cause = design_service._probe_catalog()
        assert slugs == ()
        assert cause is not None
        assert "none of them installed" in cause

    async def test_a_partial_install_is_degraded_with_a_count(self, monkeypatch):
        """Degraded, not unavailable: what is there can still be imported, and
        saying how much is missing beats a round number nobody can act on."""
        from maistro_design.systems import importer

        monkeypatch.setattr(
            importer,
            "load_catalog",
            lambda: [
                {"slug": "airbnb", "tier": "catalog"},
                {"slug": "ghost", "tier": "catalog"},
            ],
        )
        slugs, cause = design_service._probe_catalog()
        assert slugs == ("airbnb",)
        assert cause is not None and "1 of 2" in cause

    async def test_the_bundled_tier_is_still_excluded(self, monkeypatch):
        """The tier split from #293 must survive the payload check: `default`
        lives under `systems/bundled/`, so a payload probe against
        `systems/catalog/` would drop it for the wrong reason if it were ever
        counted as catalogue."""
        from maistro_design.systems import importer

        monkeypatch.setattr(
            importer,
            "load_catalog",
            lambda: [
                {"slug": "default", "tier": "bundled"},
                {"slug": "airbnb", "tier": "catalog"},
            ],
        )
        slugs, cause = design_service._probe_catalog()
        assert slugs == ("airbnb",)
        assert cause is None
