"""DesignService — singleton providing DesignEngine and PgDesignProjectStore.

Initializes maistro-design subsystems for the Conductor backend.
Wires the design engine (skill registry + system registry) and project
persistence store (PostgreSQL) as singletons accessible via get_design_engine()
and get_design_store().
"""

from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger("hive.design_service")

__all__ = [
    "DesignServiceStatus",
    "get_design_engine",
    "get_design_status",
    "get_design_store",
    "get_renderer_registry",
    "start_design_service",
    "stop_design_service",
]


@dataclass(frozen=True)
class DesignServiceStatus:
    """What startup actually achieved, as something the API can answer with.

    Before #293 this was a `logger.warning` and nothing else, so a failure to
    load the design systems was visible only to whoever read the container log
    on the right day. Every caller after that point saw a service that looked
    ready, because the code had replaced what it could not load.

    Two states, deliberately not one:

    - `ready` is about the *required* half. The bundled systems are packaged
      data, not a catalogue: if they cannot load the install is broken, the
      engine is not built, and every design route reports that with `cause`
      instead of serving a substitute.
    - `catalog_available` is about the *optional* half. The Tier-2 catalogue is
      an extra; a missing or unreadable index degrades the service rather than
      breaking it -- but it is reported as degraded, with the cause, rather
      than as an empty list that reads like "nothing to import".
    """

    ready: bool = False
    cause: str | None = None
    bundled_slugs: tuple[str, ...] = ()
    catalog_available: bool = False
    catalog_cause: str | None = None
    catalog_slugs: tuple[str, ...] = field(default=(), repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "cause": self.cause,
            "bundled_count": len(self.bundled_slugs),
            "catalog": {
                "available": self.catalog_available,
                "cause": self.catalog_cause,
                "count": len(self.catalog_slugs),
            },
        }


def _open_design_config(settings: Any | None = None) -> Any | None:
    """Build an OpenDesignConfig, or None when the plugin is disabled.

    Prefers typed ``Settings`` fields (so values from ``backend/.env`` loaded by
    pydantic-settings are honoured — those are NOT exported to ``os.environ``), and
    falls back to the process environment when no settings are supplied. Off unless
    explicitly enabled, so an install without the daemon never pays a startup probe.
    """

    def _field(name: str, env: str, default: str | None = None) -> Any:
        if settings is not None:
            value = getattr(settings, name, None)
            if value is not None:
                return value
        return os.environ.get(env, default)

    enabled = _field("open_design_enabled", "OPEN_DESIGN_ENABLED", "")
    is_on = enabled is True or str(enabled).lower() in {"1", "true", "yes", "on"}
    if not is_on:
        return None

    from maistro_design.providers import OpenDesignConfig

    token = _field("open_design_token", "OPEN_DESIGN_TOKEN")
    if hasattr(token, "get_secret_value"):  # unwrap pydantic SecretStr
        token = token.get_secret_value()

    return OpenDesignConfig(
        enabled=True,
        base_url=_field("open_design_url", "OPEN_DESIGN_URL", "http://127.0.0.1:7456"),
        token=token,
    )


@functools.lru_cache(maxsize=1)
def _get_async_engine() -> AsyncEngine | None:
    """Return an async SQLAlchemy engine for design projects, or None if DATABASE_URL is unset."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        logger.debug("DATABASE_URL not configured — design persistence disabled")
        return None
    try:
        return create_async_engine(url, pool_pre_ping=True)
    except Exception as exc:
        logger.warning("Failed to create design database engine: %s", exc)
        return None


@functools.lru_cache(maxsize=1)
def _get_async_session_factory() -> async_sessionmaker[Any] | None:
    """Return an async session factory for design projects, or None if no engine."""
    engine = _get_async_engine()
    if engine is None:
        return None
    return async_sessionmaker(engine, expire_on_commit=False)


_engine_singleton: Any = None
_store_singleton: Any = None
_renderer_registry_singleton: Any = None
_status: DesignServiceStatus = DesignServiceStatus(cause="start_design_service() has not run")


def get_design_status() -> DesignServiceStatus:
    """What startup achieved. Never raises -- this is what callers ask when
    `get_design_engine()` did."""
    return _status


def get_renderer_registry() -> Any:
    """Get the RendererRegistry singleton (renderer capability slots, SPEC-070426-a22b)."""
    if _renderer_registry_singleton is None:
        raise RuntimeError(
            "RendererRegistry not initialized — ensure start_design_service() was called in app lifespan"
        )
    return _renderer_registry_singleton


def get_design_engine() -> Any:
    """Get the DesignEngine singleton."""
    if _engine_singleton is None:
        raise RuntimeError(
            "DesignEngine not initialized — ensure start_design_service() was called in app lifespan"
        )
    return _engine_singleton


def get_design_store() -> Any:
    """Get the PgDesignProjectStore singleton."""
    if _store_singleton is None:
        raise RuntimeError(
            "DesignProjectStore not initialized — ensure start_design_service() was called in app lifespan"
        )
    return _store_singleton


async def start_design_service(settings: Settings) -> None:
    """Initialize the DesignEngine and PgDesignProjectStore singletons.

    Called during FastAPI lifespan startup.
    """
    global _engine_singleton, _store_singleton, _renderer_registry_singleton, _status

    try:
        from maistro_design.engine import DesignEngine
        from maistro_design.skills.builtins import load_builtins
        from maistro_design.skills.registry import InMemoryDesignSkillRegistry
        from maistro_design.stores import PgDesignProjectStore
        from maistro_design.systems.importer import load_bundled as load_bundled_systems
        from maistro_design.systems.registry import InMemoryDesignSystemRegistry

        # Initialize skill registry with built-in skills
        skill_registry = InMemoryDesignSkillRegistry()
        load_builtins(skill_registry)
        logger.info("Design skill registry initialized")

        # Initialize system registry with the bundled Tier-1 design systems.
        #
        # `systems.importer.load_bundled` is the real entry point, and the same
        # one `maistro_design.nodes` already uses. This used to import
        # `maistro_design.systems.builtins`, a module that has never existed in
        # any version of the package, and a bare `except Exception` turned the
        # resulting ModuleNotFoundError into a hand-built stub (#293).
        #
        # The stub was worse than an empty registry, because it answered to the
        # same name as a real system. `default` bundled carries 16 colors, 8
        # spacing tokens and TrustTier.T1; the stub carried none of either at
        # T0. Nothing downstream could tell them apart by slug, so a generation
        # against "default" proceeded with an empty palette and a different
        # trust tier -- and the other five systems (apple, editorial,
        # enterprise, material, shadcn) raised DesignSystemNotFoundError from
        # `DesignEngine`, because they were never registered at all.
        #
        # Not wrapped in its own handler now. These systems are packaged data,
        # not an optional catalog: if they cannot load, the install is broken,
        # and the outer handler below records that with its cause rather than
        # inventing a product to ship in their place.
        system_registry = InMemoryDesignSystemRegistry()
        load_bundled_systems(system_registry)
        bundled = tuple(sorted(system.slug for system in system_registry.list_all()))
        logger.info(
            "Design system registry initialized with %d bundled system(s): %s",
            len(bundled),
            ", ".join(bundled),
        )

        # The Tier-2 catalogue, in contrast, IS optional -- 144 systems a user
        # may import one at a time, none of them registered at startup. Probed
        # here only so its absence is reported as degraded with a cause rather
        # than surfacing as an empty list, which reads like "nothing to
        # import" and is the quieter cousin of the same defect.
        catalog_slugs, catalog_cause = _probe_catalog()

        # Initialize project store if database is available
        project_store: Any | None = None
        session_factory = _get_async_session_factory()
        if session_factory is not None:
            project_store = PgDesignProjectStore(session_factory=session_factory)
            logger.info("Design project store initialized with PostgreSQL")
        else:
            logger.info("Design project store disabled (no DATABASE_URL configured)")

        # Initialize design engine with registries and optional store
        _engine_singleton = DesignEngine(
            skill_registry=skill_registry,
            system_registry=system_registry,
            project_store=project_store,
        )
        _store_singleton = project_store
        logger.info("DesignEngine initialized")

        # Renderer capability registry (SPEC-070426-a22b): discover optional external
        # providers so absent ones silently drop their skills from /design/skills.
        from maistro_design.providers import OpenDesignProvider
        from maistro_design.renderers import RendererRegistry

        registry = RendererRegistry()
        od_config = _open_design_config(settings)
        if od_config is not None:
            registry.register(OpenDesignProvider(od_config))
        filled = await registry.discover_all()
        _renderer_registry_singleton = registry
        logger.info("Renderer slots available: %s", sorted(s.value for s in filled))

        _status = DesignServiceStatus(
            ready=True,
            bundled_slugs=bundled,
            catalog_available=catalog_cause is None,
            catalog_cause=catalog_cause,
            catalog_slugs=catalog_slugs,
        )

    # Both handlers still catch, because a Conductor install without
    # maistro-design is supported and must not take the whole app down. What
    # changed in #293 is what they leave behind: a recorded cause the design
    # routes answer with, instead of a log line and a service that looks ready.
    except ImportError as exc:
        logger.warning("maistro-design not installed or unavailable: %s", exc)
        _status = DesignServiceStatus(cause=f"maistro-design is not installed: {exc}")
    except Exception as exc:
        logger.warning("DesignService initialization failed: %s", exc, exc_info=True)
        _status = DesignServiceStatus(cause=f"{type(exc).__name__}: {exc}")


def _probe_catalog() -> tuple[tuple[str, ...], str | None]:
    """The importable Tier-2 slugs, or the reason they cannot be listed.

    Filtered by the index's own `tier` field. The index covers both tiers --
    150 entries, six of which are the bundled systems living under
    `systems/bundled/` -- and `import_from_catalog` reads `systems/catalog/`
    only, so returning the index verbatim would offer six systems that cannot
    be imported from the path the offer implies.
    """
    from maistro_design.systems.importer import ORIGIN_CATALOG, load_catalog

    try:
        entries = load_catalog()
    except Exception as exc:
        logger.warning("Tier-2 design system catalog unavailable: %s", exc)
        return (), f"{type(exc).__name__}: {exc}"

    slugs = tuple(
        sorted(
            str(entry["slug"])
            for entry in entries
            if entry.get("tier") == ORIGIN_CATALOG and entry.get("slug")
        )
    )
    logger.info("Tier-2 design system catalog available: %d system(s)", len(slugs))
    return slugs, None


async def stop_design_service() -> None:
    """Cleanup the DesignService singletons."""
    global _engine_singleton, _store_singleton, _renderer_registry_singleton, _status
    _status = DesignServiceStatus(cause="stop_design_service() has run")
    _engine_singleton = None
    _store_singleton = None
    _renderer_registry_singleton = None
    _get_async_engine.cache_clear()
    _get_async_session_factory.cache_clear()
    try:
        from services.design_preview import _singleton as preview_singleton

        if preview_singleton is not None:
            logger.info("DesignPreviewService stopped")
    except Exception:
        pass
