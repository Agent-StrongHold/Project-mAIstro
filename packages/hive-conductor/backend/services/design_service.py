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
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger("hive.design_service")


class DesignStoreConfigurationError(RuntimeError):
    """A database URL is configured, but an async engine could not be built.

    Distinct from "no URL configured" (#1826). The engine factory used to turn
    every creation failure into `None`, and startup then described a configured
    database in exactly the words it uses for a missing one -- "disabled (no
    DATABASE_URL configured)" -- so a driver or URL defect wore the costume of
    a deliberate absence, and the store was simply off on the shipped
    Compose configuration.

    The message carries the exception's type name against a redacted URL and
    never `str(exc)`: SQLAlchemy's parse errors interpolate the URL they
    could not parse, credentials and all, and this sentence lands in logs.
    """


__all__ = [
    "DesignServiceStatus",
    "DesignStoreConfigurationError",
    "get_design_canonical_execution",
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
    #: Why there is no project store, when the reason is *not* absence (#1826).
    #: None with a store means operational; None without one means nothing was
    #: configured; set means a URL was configured and failed, and this is its
    #: sanitized cause -- the string the project routes answer with, in place
    #: of the no-database message that used to cover both.
    store_cause: str | None = None
    #: Whether the canonical Goal->Graph->Run execution binding came up (#52).
    canonical_execution_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "cause": self.cause,
            "store_cause": self.store_cause,
            "bundled_count": len(self.bundled_slugs),
            "catalog": {
                "available": self.catalog_available,
                "cause": self.catalog_cause,
                "count": len(self.catalog_slugs),
            },
            "canonical_execution_available": self.canonical_execution_available,
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
    """Return an async SQLAlchemy engine, or None if no database is configured.

    Routed through the shared config contract rather than a raw `DATABASE_URL`
    read (#1826). Compose provides `postgresql://...`, and handed bare to
    `create_async_engine` that scheme selects psycopg2 -- a synchronous driver,
    absent from the async runtime -- so creation raised `ModuleNotFoundError`,
    the old `except` swallowed it into `None`, and startup reported the store
    disabled as if no database had been configured at all. This is the same
    pair of helpers `maistro.memory.store.get_engine` runs: `resolve_database_url`
    answers "which database" (the `DATABASE_URL` Compose sets, or the `DB_*`
    set it can compose), `to_async_url` answers "which driver", and no scheme
    rules are invented here.

    `None` means nothing is configured -- the supported no-database mode. A
    URL that is configured but fails resolution/validation (a `DB_*` value
    pydantic rejects) or cannot build an engine raises
    `DesignStoreConfigurationError`, so the failure reports as what it is
    instead of becoming absence downstream.
    """
    from maistro.config.database import resolve_database_url, to_async_url

    try:
        url = to_async_url(resolve_database_url())
    except Exception as exc:
        # Resolution is persistence-scoped too (#1826 review): a `DB_*` value
        # that fails validation must reach the store-specific handler as a
        # `DesignStoreConfigurationError`, not escape startup as a raw
        # `ValidationError` and mark the whole service unready. Type name
        # only -- same rule as `_store_failure_cause`, the message never
        # interpolates the environment it failed on.
        raise DesignStoreConfigurationError(
            f"database URL could not be resolved from the environment: {type(exc).__name__}"
        ) from exc
    if not url:
        logger.debug("No database URL configured — design persistence disabled")
        return None
    try:
        return create_async_engine(url, pool_pre_ping=True)
    except Exception as exc:
        logger.warning(
            "Failed to create design database engine for %s: %s",
            _redacted_url(url),
            type(exc).__name__,
        )
        raise DesignStoreConfigurationError(_store_failure_cause(url, exc)) from exc


def _redacted_url(url: str) -> str:
    """The URL with its credentials dropped, for anything a human might read.

    `maistro.container._redact_url` is the shared implementation -- the one
    `maistro.config.database` itself reaches for. Two inputs defeat it, and
    both fall back to the scheme alone, because a string whose credentials
    cannot be promised away must not be echoed at all:

    - inputs that helper cannot parse without raising (a URL whose port is
      not a number makes `urlsplit(...).port` raise `ValueError`);
    - inputs it returns unchanged, which is exactly its no-netloc case: a
      malformed `postgresql:user:secret@host/db` (no `//`) files the whole
      credential-bearing tail under *path*, so the helper hands it back
      verbatim (#1826 review). ADR-064's log scrubber cannot rescue it
      either -- its userinfo pattern anchors on `://`, which this spelling
      does not contain.

    A broken deployment is exactly as likely to have typed one of those as a
    working URL, and a diagnostics path that dies on -- or leaks -- its own
    input reports nothing, or reports too much.
    """

    def _scheme_only() -> str:
        return f"{url.split(':', 1)[0]}:<unparseable>"

    try:
        from maistro.container import _redact_url

        redacted = str(_redact_url(url))
    except Exception:
        return _scheme_only()
    if not urlsplit(url).netloc:
        # No authority component, so nothing was parsed as userinfo and the
        # helper echoed its input. The credentials -- wherever they sit in
        # the string -- survive only in what this returns, not in it.
        return _scheme_only()
    return redacted


def _store_failure_cause(url: str, exc: Exception) -> str:
    """The sanitized sentence a configured-but-broken database reports.

    The exception's *type*, never `str(exc)`: a parse failure interpolates the
    URL it could not parse, credentials and all.
    """
    return (
        f"database URL {_redacted_url(url)!r} is configured, but the async "
        f"engine failed to build: {type(exc).__name__}"
    )


@functools.lru_cache(maxsize=1)
def _get_async_session_factory() -> async_sessionmaker[Any] | None:
    """Return an async session factory for design projects, or None if no engine.

    Propagates `DesignStoreConfigurationError`: a configured-but-broken URL is
    not absence, and the caller that can degrade is the one that decides how
    (#1826).
    """
    engine = _get_async_engine()
    if engine is None:
        return None
    return async_sessionmaker(engine, expire_on_commit=False)


_engine_singleton: Any = None
_store_singleton: Any = None
_renderer_registry_singleton: Any = None
_canonical_execution_singleton: Any = None
# Adapters cached per authorized Workspace (#52 review): admission scope is
# resolved from the request principal, never from the startup binding.
_canonical_execution_adapters: dict[str, Any] = {}
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


def get_design_canonical_execution() -> Any | None:
    """Return the startup wiring probe, if the spine is wired.

    Not an admission scope. The singleton exists to decide, once, whether the
    Run/NodeRun/Attempt spine is reachable; its Workspace binding is the
    deployment's own default and must never stand in for a caller's
    authorization. Route admission resolves scope per principal via
    `get_design_canonical_execution_for_principal`.
    """
    return _canonical_execution_singleton


async def get_design_canonical_execution_for_principal(principal_id: str) -> Any | None:
    """The canonical Design adapter bound to the caller's authorized Workspace.

    Design offers no caller-named Workspace selection, so the caller's own
    default Workspace — which `resolve_default_workspace` guarantees they own,
    the same fallback chat admission applies — is the scope every Run files
    into. A principal is never filed into a Workspace they hold no membership
    in, and the adapter is cached per Workspace like chat's admitters.
    """
    if not isinstance(principal_id, str) or not principal_id.strip():
        return None
    from services.default_workspace import resolve_default_workspace
    from services.engine import get_engine

    try:
        core_engine = get_engine()
    except RuntimeError:
        return None
    run_store = getattr(core_engine, "run_store", None)
    scope_store = getattr(core_engine, "project_scope_store", None)
    if run_store is None or scope_store is None:
        return None
    workspace_id = (await resolve_default_workspace(principal_id)).id
    adapter = _canonical_execution_adapters.get(workspace_id)
    if adapter is None:
        from maistro_design.canonical_execution import DesignCanonicalExecution

        root = await scope_store.create_root(workspace_id)
        adapter = DesignCanonicalExecution(
            run_store,
            workspace_id=workspace_id,
            project_id=root.project_id,
        )
        _canonical_execution_adapters[workspace_id] = adapter
    return adapter


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
    global _canonical_execution_singleton, _status
    _canonical_execution_singleton = None

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
        store_cause: str | None = None
        try:
            session_factory: async_sessionmaker[Any] | None = _get_async_session_factory()
        except DesignStoreConfigurationError as exc:
            # A configured URL that cannot build an engine (#1826). Degrade to
            # no store -- the systems half of this service needs no database --
            # but record *why*, so the project routes answer with the actual
            # sanitized failure and the log says so, instead of both describing
            # a configured database as if it had never been named.
            session_factory = None
            store_cause = str(exc)
            logger.warning("Design project store unavailable: %s", store_cause)
        if session_factory is not None:
            project_store = PgDesignProjectStore(session_factory=session_factory)
            logger.info("Design project store initialized with PostgreSQL")
        elif store_cause is None:
            logger.info("Design project store disabled (no database URL configured)")

        # Initialize design engine with registries and optional store.
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

        # Design is a projection over the canonical spine. In degraded/demo
        # mode there may be no in-process RunStore; leave the action unavailable
        # rather than fabricating a successful local lifecycle.
        try:
            from maistro_design.canonical_execution import DesignCanonicalExecution
            from services.engine import get_engine

            core_engine = get_engine()
            run_store = core_engine.run_store
            scope_store = core_engine.project_scope_store
            workspace_id = str(getattr(settings, "hive_default_workspace_id", "") or "")
            if run_store is not None and scope_store is not None and workspace_id:
                # A wiring probe, not an admission scope (#52 review): this
                # proves the spine answers (`create_root` is idempotent
                # create-or-return) before the status claims availability.
                # Per-caller scope is resolved from the request principal at
                # admission time, never from this deployment-wide binding.
                root = await scope_store.create_root(workspace_id)
                _canonical_execution_singleton = DesignCanonicalExecution(
                    run_store,
                    workspace_id=workspace_id,
                    project_id=root.project_id,
                )
        except Exception as exc:
            logger.info("Design canonical execution unavailable: %s", exc)

        _status = DesignServiceStatus(
            ready=True,
            bundled_slugs=bundled,
            catalog_available=catalog_cause is None,
            catalog_cause=catalog_cause,
            catalog_slugs=catalog_slugs,
            store_cause=store_cause,
            canonical_execution_available=_canonical_execution_singleton is not None,
        )

    # Both handlers still catch, because a Conductor install without
    # maistro-design is supported and must not take the whole app down. What
    # changed in #293 is what they leave behind: a recorded cause the design
    # routes answer with, instead of a log line and a service that looks ready.
    except ImportError as exc:
        logger.warning("maistro-design not installed or unavailable: %s", exc)
        _canonical_execution_singleton = None
        _status = DesignServiceStatus(cause=f"maistro-design is not installed: {exc}")
    except Exception as exc:
        logger.warning("DesignService initialization failed: %s", exc, exc_info=True)
        _canonical_execution_singleton = None
        _status = DesignServiceStatus(cause=f"{type(exc).__name__}: {exc}")


def _importable(slug: str) -> bool:
    """Whether one catalogue slug's files are present *and* parse.

    The same reads and the same JSON parse `import_from_catalog` performs, so
    the answer means what the word says. Deliberately not a call into the
    importer itself: that also runs the content scan and registers the system,
    and a startup probe must do neither.
    """
    import json

    from maistro_design.systems.importer import CATALOG_ROOT, ESSENTIAL_FILES

    directory = CATALOG_ROOT / slug
    for name in ESSENTIAL_FILES:
        if name == "design-tokens.json":
            continue  # optional, exactly as the importer treats it
        path = directory / name
        if not path.is_file():
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        if name.endswith(".json"):
            try:
                json.loads(text)
            except ValueError:
                return False
        elif not text.strip():
            return False
    return True


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

    indexed = sorted(
        str(entry["slug"])
        for entry in entries
        if entry.get("tier") == ORIGIN_CATALOG and entry.get("slug")
    )

    # The index is a claim; the files are the fact (#413). `import_from_catalog`
    # reads `systems/catalog/<slug>/`, not the index, so a build carrying
    # catalog.json without the payloads would advertise 144 importable systems
    # and fail every one on click.
    #
    # Existence is not enough either (#413 review): the importer *parses* what
    # it reads, so a present-but-malformed `manifest.json` gets advertised and
    # then fails on selection. `_importable` performs the same reads and the
    # same parse, which is the only thing that earns the word "importable".
    present = [slug for slug in indexed if _importable(slug)]
    missing = len(indexed) - len(present)
    if not present:
        cause = f"catalog index lists {len(indexed)} system(s), none of them installed"
        logger.warning("Tier-2 design system catalog unavailable: %s", cause)
        return (), cause
    if missing:
        # Degraded, not unavailable: what is there can still be imported, and
        # saying so beats reporting a round number nobody can act on.
        cause = f"{missing} of {len(indexed)} indexed system(s) have no files installed"
        logger.warning("Tier-2 design system catalog partially installed: %s", cause)
        return tuple(present), cause
    logger.info("Tier-2 design system catalog available: %d system(s)", len(present))
    return tuple(present), None


async def stop_design_service() -> None:
    """Cleanup the DesignService singletons."""
    global _engine_singleton, _store_singleton, _renderer_registry_singleton
    global _canonical_execution_singleton, _status
    _status = DesignServiceStatus(cause="stop_design_service() has run")
    _engine_singleton = None
    _store_singleton = None
    _renderer_registry_singleton = None
    _canonical_execution_singleton = None
    _canonical_execution_adapters.clear()
    _get_async_engine.cache_clear()
    _get_async_session_factory.cache_clear()
    try:
        from services.design_preview import _singleton as preview_singleton

        if preview_singleton is not None:
            logger.info("DesignPreviewService stopped")
    except Exception:
        pass
