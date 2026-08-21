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
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger("hive.design_service")

__all__ = [
    "get_design_engine",
    "get_design_store",
    "get_renderer_registry",
    "start_design_service",
    "stop_design_service",
]


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
    global _engine_singleton, _store_singleton, _renderer_registry_singleton

    try:
        from maistro_design.engine import DesignEngine
        from maistro_design.skills.builtins import load_builtins
        from maistro_design.skills.registry import InMemoryDesignSkillRegistry
        from maistro_design.stores import PgDesignProjectStore
        from maistro_design.systems.registry import InMemoryDesignSystemRegistry
        from maistro_design.trust import TrustTier
        from maistro_design.types import DesignSystem

        # Initialize skill registry with built-in skills
        skill_registry = InMemoryDesignSkillRegistry()
        load_builtins(skill_registry)
        logger.info("Design skill registry initialized")

        # Initialize system registry with bundled systems
        system_registry = InMemoryDesignSystemRegistry()
        try:
            from maistro_design.systems.builtins import load_builtins as load_system_builtins

            load_system_builtins(system_registry)
            logger.info("Design system registry initialized with bundled systems")
        except Exception as exc:
            logger.warning("Failed to load bundled design systems, using default: %s", exc)
            system_registry.register(
                DesignSystem(
                    slug="default",
                    name="Default",
                    description="Neutral default design system",
                    trust_tier=TrustTier.T0,
                )
            )

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

    except ImportError as exc:
        logger.warning("maistro-design not installed or unavailable: %s", exc)
    except Exception as exc:
        logger.warning("DesignService initialization failed: %s", exc, exc_info=True)


async def stop_design_service() -> None:
    """Cleanup the DesignService singletons."""
    global _engine_singleton, _store_singleton, _renderer_registry_singleton
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
