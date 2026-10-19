"""The Design store's database URL is normalized before its engine is built (#1826).

Compose provides Hive a `postgresql://...` DATABASE_URL. Handed bare to
`create_async_engine`, that scheme selects psycopg2 — a synchronous driver,
absent from the async runtime — so engine creation raised, `_get_async_engine`'s
old `except` turned it into `None`, and startup then described a configured
database in exactly the words it uses for a missing one. Persistence was off on
the shipped configuration, silently, with a log line claiming it was deliberate.

Everything here runs without a database: `create_async_engine` selects a
dialect from the URL alone, so which driver a URL *would* drive is provable
from the engine object, and every failure below is forced at the factory
boundary. The database-touching half of #1826 lives in
`test_design_supported_path.py`.
"""

from __future__ import annotations

import logging
import pathlib
import sys

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException  # noqa: E402
from routes import design as design_routes  # noqa: E402
from services import design_service  # noqa: E402

#: The exact spelling docker-compose.yml hands the hive service
#: (`DATABASE_URL=postgresql://maistro:${DB_PASSWORD}@postgres:5432/maistro`).
COMPOSE_URL = "postgresql://maistro:s3cret@postgres:5432/maistro"

#: Every PostgreSQL spelling the canonical normalizer accepts
#: (`maistro.config.database._MIGRATABLE_SCHEMES`). A spelling accepted at the
#: config boundary must reach the engine boundary as the same database.
SUPPORTED_SPELLINGS = [
    "postgresql://maistro:s3cret@postgres:5432/maistro?sslmode=require",
    "postgres://maistro:s3cret@postgres:5432/maistro?sslmode=require",
    "postgresql+asyncpg://maistro:s3cret@postgres:5432/maistro?sslmode=require",
    "postgresql+psycopg://maistro:s3cret@postgres:5432/maistro?sslmode=require",
]

_DB_ENV = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


@pytest.fixture
def clean_wiring(monkeypatch: pytest.MonkeyPatch):
    """A clean engine cache and no inherited database environment.

    `_get_async_engine` is an lru_cache over the process environment; without
    the clear, whichever test ran first with a configured URL would answer for
    every test after it. The `DB_*` set matters too: `resolve_database_url`
    composes a URL from them, so an exported `DB_HOST` would turn the
    "nothing configured" case into a configured one.
    """
    design_service._get_async_engine.cache_clear()
    design_service._get_async_session_factory.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in _DB_ENV:
        monkeypatch.delenv(name, raising=False)
    yield
    design_service._get_async_engine.cache_clear()
    design_service._get_async_session_factory.cache_clear()


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch, clean_wiring):
    """The singletons `start_design_service` leaves behind, restored after.

    The engine/store singletons are module globals; monkeypatch restores them
    so a test cannot change what the next one measures (same contract as
    `test_design_service_startup`'s `engine` fixture).
    """
    monkeypatch.setattr(design_service, "_engine_singleton", None)
    monkeypatch.setattr(design_service, "_store_singleton", None)
    monkeypatch.setattr(design_service, "_renderer_registry_singleton", None)
    monkeypatch.setattr(design_service, "_status", design_service.DesignServiceStatus())
    return monkeypatch


class _Settings:
    open_design_url = None
    open_design_api_key = None


class TestTheComposeSpellingBuildsTheAsyncEngine:
    """The shipped environment spelling, at the service's own boundary."""

    async def test_the_compose_url_drives_asyncpg(self, started, monkeypatch):
        """The regression, stated as production behavior: the URL Compose
        emits must produce an engine whose dialect is the supported async
        driver. Under the old code this raised `ModuleNotFoundError` for
        psycopg2 inside `create_async_engine` and the store silently went
        away; with psycopg2 installed it would silently build a *synchronous*
        engine instead — either way `driver` is the tell."""
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL)
        engine = design_service._get_async_engine()
        assert engine is not None
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "asyncpg"

    async def test_the_session_factory_follows_the_engine(self, started, monkeypatch):
        """A store needs the factory, not the engine; if the engine had failed
        the old way, this returned `None` and startup called that deliberate."""
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL)
        assert design_service._get_async_session_factory() is not None


class TestSupportedSpellingsNormalizeConsistently:
    """Every spelling the canonical config contract accepts reaches the engine
    boundary as the same database: asyncpg-driven, with credentials, host,
    port, database and query data exactly as configured."""

    @pytest.mark.parametrize("url", SUPPORTED_SPELLINGS)
    async def test_a_supported_spelling_drives_asyncpg_unchanged(self, started, monkeypatch, url):
        monkeypatch.setenv("DATABASE_URL", url)
        engine = design_service._get_async_engine()
        assert engine is not None
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "asyncpg"
        # The normalization's whole contract: driver suffix only. Anything
        # else changed would be a rewrite dressed as a normalization.
        assert engine.url.username == "maistro"
        assert engine.url.password == "s3cret"
        assert engine.url.host == "postgres"
        assert engine.url.port == 5432
        assert engine.url.database == "maistro"
        assert dict(engine.url.query) == {"sslmode": "require"}


class TestAnAbsentUrlIsExplicitlyUnavailable:
    """The no-database mode stays a supported, deliberate state."""

    async def test_no_configuration_disables_the_store(self, clean_wiring):
        assert design_service._get_async_engine() is None
        assert design_service._get_async_session_factory() is None

    async def test_startup_reports_absence_as_absence(self, started):
        """`store_cause` stays None: absence is not a failure, and the route's
        no-database answer is the honest one for it."""
        await design_service.start_design_service(_Settings())
        status = design_service.get_design_status()
        assert status.ready
        assert status.store_cause is None
        # `get_design_store` raises rather than returning None — the same
        # signal the routes normalize into their 503.
        with pytest.raises(RuntimeError, match="not initialized"):
            design_service.get_design_store()

    async def test_the_route_answers_no_database_when_absent(self, started):
        await design_service.start_design_service(_Settings())
        with pytest.raises(HTTPException) as excinfo:
            design_routes._require_store()
        assert excinfo.value.status_code == 503
        assert "no database URL configured" in excinfo.value.detail


class TestConfiguredButBrokenIsNeverAbsence:
    """The defect's second half: a URL that cannot build an engine must report
    its own failure — sanitized — and never wear the no-database message."""

    async def test_a_driver_failure_raises_as_configuration(self, started, monkeypatch):
        """The exact failure the Compose spelling used to produce, forced at
        the factory: it comes back as `DesignStoreConfigurationError`, not as
        `None` that startup later relabels."""
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL)

        def _broken(*args: object, **kwargs: object) -> None:
            raise ModuleNotFoundError("No module named 'psycopg2'")

        monkeypatch.setattr(design_service, "create_async_engine", _broken)
        with pytest.raises(design_service.DesignStoreConfigurationError) as excinfo:
            design_service._get_async_session_factory()
        message = str(excinfo.value)
        assert "ModuleNotFoundError" in message
        assert "postgres:5432" in message

    async def test_a_malformed_url_reports_sanitized(self, started, monkeypatch):
        """A real SQLAlchemy refusal — the port column is not a number — with
        no monkeypatching: the failure path production would take. The cause
        names the scheme and the exception, and the password survives nowhere
        in it, even though SQLAlchemy's own error text may echo the URL."""
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL.replace("5432", "notaport"))
        with pytest.raises(design_service.DesignStoreConfigurationError) as excinfo:
            design_service._get_async_engine()
        message = str(excinfo.value)
        assert "failed to build" in message
        assert "s3cret" not in message

    async def test_a_netloc_less_url_is_never_echoed(self, started, monkeypatch, caplog):
        """A `DATABASE_URL` missing the `//` (e.g. `postgresql:user:secret@host/db`)
        defeats the shared `_redact_url` differently: `urlsplit` files the whole
        credential-bearing tail under *path* and reports an empty netloc, so the
        helper returns its input unchanged instead of raising — the fallback for
        a raised ValueError never fires. Both consumers interpolate this result:
        the warning log and `store_cause`, which the project routes return in
        their 503 detail. ADR-064's scrubber cannot rescue the log either (its
        userinfo pattern anchors on `://`). So a no-netloc result must be
        treated as unparseable: scheme only, credentials nowhere."""
        netloc_less = "postgresql:user:secret@host/db"
        monkeypatch.setenv("DATABASE_URL", netloc_less)
        with (
            caplog.at_level(logging.WARNING, logger="hive.design_service"),
            pytest.raises(design_service.DesignStoreConfigurationError) as excinfo,
        ):
            design_service._get_async_engine()
        message = str(excinfo.value)
        assert "postgresql:<unparseable>" in message
        assert "secret" not in message
        assert netloc_less not in message
        assert all("secret" not in record.getMessage() for record in caplog.records)

    async def test_startup_degrades_with_the_recorded_cause(self, started, monkeypatch):
        """The service stays ready — the systems half needs no database — but
        the store is gone *with its cause*, and startup says configured-and-
        broken in the log's own words, not the no-database ones."""
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL)

        def _broken(*args: object, **kwargs: object) -> None:
            raise ModuleNotFoundError("No module named 'psycopg2'")

        monkeypatch.setattr(design_service, "create_async_engine", _broken)
        await design_service.start_design_service(_Settings())
        status = design_service.get_design_status()
        assert status.ready
        with pytest.raises(RuntimeError, match="not initialized"):
            design_service.get_design_store()
        assert status.store_cause is not None
        assert "ModuleNotFoundError" in status.store_cause
        assert "s3cret" not in status.store_cause

    async def test_the_route_answers_with_the_actual_failure(self, started, monkeypatch):
        """Never relabeled: the project routes must return the recorded cause
        where they used to return "DATABASE_URL not set" for a database that
        had very much been set."""
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL)

        def _broken(*args: object, **kwargs: object) -> None:
            raise ModuleNotFoundError("No module named 'psycopg2'")

        monkeypatch.setattr(design_service, "create_async_engine", _broken)
        await design_service.start_design_service(_Settings())
        with pytest.raises(HTTPException) as excinfo:
            design_routes._require_store()
        assert excinfo.value.status_code == 503
        assert "ModuleNotFoundError" in excinfo.value.detail
        assert "not set" not in excinfo.value.detail
        assert "s3cret" not in excinfo.value.detail

    async def test_the_none_returning_store_seam_answers_with_the_cause_too(
        self, started, monkeypatch
    ):
        """`_require_store` normalizes two unavailable forms: the accessor's
        RuntimeError and a None store. Both must answer a recorded cause with
        that cause. The current accessor can only raise, so the None form is
        the seam older callers (and the AC-6 scope tests) exercise — but if it
        ever yielded None under a recorded failure, answering "no database URL
        configured" would be the same conflation #1826 forbids, one seam over.
        The assertion that discriminates is the positive one: the detail must
        name the actual failure, not merely avoid the old "not set" words."""
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL)

        def _broken(*args: object, **kwargs: object) -> None:
            raise ModuleNotFoundError("No module named 'psycopg2'")

        monkeypatch.setattr(design_service, "create_async_engine", _broken)
        await design_service.start_design_service(_Settings())
        assert design_service.get_design_status().store_cause is not None
        monkeypatch.setattr(design_routes, "get_design_store", lambda: None)
        with pytest.raises(HTTPException) as excinfo:
            design_routes._require_store()
        assert excinfo.value.status_code == 503
        assert "ModuleNotFoundError" in excinfo.value.detail
        assert "no database URL configured" not in excinfo.value.detail
        assert "s3cret" not in excinfo.value.detail


class TestAResolutionFailureIsAlsoConfiguration:
    """Resolution is persistence-scoped too (#1826 salvage review).

    `resolve_database_url` composes a URL from a `DB_*` set through pydantic,
    so a value it rejects -- `DB_PORT=notaport`, say -- raises
    `ValidationError` before any URL exists to build an engine from. Uncaught,
    that error sailed past the store-scoped `except
    DesignStoreConfigurationError` in `start_design_service` into the outer
    handler, and a database typo marked the whole service -- the systems half
    included -- unready.
    """

    async def test_an_invalid_db_value_raises_as_configuration(self, started, monkeypatch):
        """The failure surfaces as `DesignStoreConfigurationError`, naming the
        exception type and never the environment value that caused it -- the
        same sanitization rule as the engine-build path."""
        monkeypatch.setenv("DB_PORT", "notaport")
        with pytest.raises(design_service.DesignStoreConfigurationError) as excinfo:
            design_service._get_async_session_factory()
        message = str(excinfo.value)
        assert "could not be resolved" in message
        assert "ValidationError" in message
        assert "notaport" not in message

    async def test_startup_degrades_only_the_store(self, started, monkeypatch):
        """The systems half stays ready; the store is gone *with its cause*,
        and the route answers with the actual failure -- never the no-database
        words, never a durable success."""
        monkeypatch.setenv("DB_PORT", "notaport")
        await design_service.start_design_service(_Settings())
        status = design_service.get_design_status()
        assert status.ready
        assert status.store_cause is not None
        assert "ValidationError" in status.store_cause
        with pytest.raises(RuntimeError, match="not initialized"):
            design_service.get_design_store()
        with pytest.raises(HTTPException) as excinfo:
            design_routes._require_store()
        assert excinfo.value.status_code == 503
        assert "ValidationError" in excinfo.value.detail
        assert "not set" not in excinfo.value.detail


class TestTheStatusCarriesTheCauseToTheApi:
    """`DesignServiceStatus.to_dict` is what the status endpoint serializes;
    a cause that never crosses that boundary cannot be answered with."""

    async def test_a_broken_store_appears_in_the_dict(self, started, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", COMPOSE_URL)

        def _broken(*args: object, **kwargs: object) -> None:
            raise ModuleNotFoundError("No module named 'psycopg2'")

        monkeypatch.setattr(design_service, "create_async_engine", _broken)
        await design_service.start_design_service(_Settings())
        payload = design_service.get_design_status().to_dict()
        assert payload["store_cause"] is not None
        assert "ModuleNotFoundError" in payload["store_cause"]

    async def test_an_absent_store_is_none_in_the_dict(self, started):
        await design_service.start_design_service(_Settings())
        assert design_service.get_design_status().to_dict()["store_cause"] is None
