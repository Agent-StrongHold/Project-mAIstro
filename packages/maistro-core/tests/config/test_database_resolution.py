"""Alembic and the container resolve the same database (#187).

They did not. `alembic/env.py` read `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/
`DB_PASSWORD` through `DatabaseSettings`; `maistro.container` read
`DATABASE_URL`; nothing mapped one onto the other. Setting only `DB_*` therefore
migrated one database and ran with in-memory stores. Both commands succeeded,
the schema was correct, and the data was discarded on every restart.

`docker-compose.yml` gives `maistro-engine` exactly those five `DB_*` variables
and no `DATABASE_URL`, so that was the shipped default rather than a
misconfiguration someone had to invent.

**The tests that matter here are the divergence tests**, not the precedence
ones. A suite that sets both spellings and checks the resolved value passes
today, because the bug was never in either path on its own — it was in the two
paths disagreeing. So the cases below configure *one* spelling at a time and
assert the other consumer follows.
"""

from __future__ import annotations

import pytest

from maistro.config.database import (
    require_database_url,
    resolve_database_url,
    to_async_url,
    to_sync_url,
)
from maistro.config.settings import DatabaseSettings
from maistro.types.errors import ConfigError

DB_ENV = {
    "DB_HOST": "db.internal",
    "DB_PORT": "5433",
    "DB_NAME": "maistro_prod",
    "DB_USER": "maistro",
    "DB_PASSWORD": "s3cret",
}


@pytest.fixture(autouse=True)
def clean_database_env(monkeypatch):
    """No inherited database configuration — these tests set their own.

    `get_engine` is `lru_cache`d, so one test's engine would otherwise be
    another's answer regardless of the environment it set.
    """
    from maistro.memory.store import reset_engine_cache

    for name in ("DATABASE_URL", *DB_ENV):
        monkeypatch.delenv(name, raising=False)
    reset_engine_cache()
    yield
    reset_engine_cache()


def _set(monkeypatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)


class TestTheTwoConsumersCannotDisagree:
    """The regression guards for the actual bug."""

    def test_db_star_alone_resolves_to_a_real_database(self, monkeypatch) -> None:
        """The shipped `docker-compose.yml` case. This returned `""` for the
        container while alembic happily migrated `db.internal`."""
        _set(monkeypatch, **DB_ENV)

        assert resolve_database_url() == (
            "postgresql+psycopg://maistro:s3cret@db.internal:5433/maistro_prod"
        )

    def test_the_loader_sees_what_alembic_sees(self, monkeypatch) -> None:
        """`config.loader` is what puts `database_url` on `AgentConfig`, and it
        used to read `os.getenv("DATABASE_URL")` directly. With only `DB_*` set
        that was `None`, so the container fell to its ephemeral branch while
        alembic used the same five variables to pick a server."""
        from maistro.config.loader import _apply_env_overrides

        _set(monkeypatch, **DB_ENV)
        raw: dict[str, object] = {}
        _apply_env_overrides(raw)

        assert raw["database_url"] == resolve_database_url()
        assert raw["database_url"] != ""

    def test_alembic_does_not_read_the_database_environment_itself(self) -> None:
        """A structural guard, because the behavioural one cannot run: importing
        `alembic/env.py` executes migrations at module level.

        What this pins is the shape of the fix rather than a value — the moment
        `env.py` constructs `DatabaseSettings` again, the two consumers can
        drift again, and every value-based test here would still pass.
        """
        import ast
        from pathlib import Path

        env_py = Path(__file__).resolve().parents[4] / "alembic" / "env.py"
        tree = ast.parse(env_py.read_text())

        # The AST rather than the text: `env.py` names `DatabaseSettings` in a
        # docstring explaining why it no longer calls it, and a substring check
        # cannot tell an explanation from a use.
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }

        assert "DatabaseSettings" not in called | imported
        assert "require_database_url" in imported

    def test_the_servers_engine_factory_sees_what_alembic_sees(self, monkeypatch) -> None:
        """The last mile, and the one that made the rest academic.

        `maistro_server.main` calls `memory.store.get_engine()` at startup, and
        it read `DATABASE_URL` directly -- so the shipped `docker-compose.yml`,
        which passes five `DB_*` variables and no `DATABASE_URL`, migrated the
        composed PostgreSQL URL while the server built no engine at all. That
        is exactly the divergence this issue is about, surviving in the real
        server path.
        """
        import maistro.memory.store as store

        _set(monkeypatch, **DB_ENV)
        captured: dict[str, str] = {}
        monkeypatch.setattr(
            store, "create_async_engine", lambda url, **_: captured.setdefault("url", url)
        )

        store.get_engine()

        assert captured["url"] == to_async_url(resolve_database_url())
        assert "db.internal" in captured["url"], "the DB_* host, not an ambient default"

    def test_the_engine_factory_still_returns_none_when_nothing_is_configured(
        self,
    ) -> None:
        """Unset stays unset. The container may legitimately run ephemeral, and
        this must not start inventing a localhost engine for it."""
        import maistro.memory.store as store

        assert store.get_engine() is None


class TestPrecedence:
    def test_database_url_wins_over_db_star(self, monkeypatch) -> None:
        """`DATABASE_URL` is authoritative because it is the only form that can
        express `sqlite:` or `memory://` — `DatabaseSettings.url` hardcodes the
        PostgreSQL scheme, so the other direction would make those
        inexpressible."""
        _set(monkeypatch, **DB_ENV, DATABASE_URL="postgresql://u:p@elsewhere/db")

        assert resolve_database_url() == "postgresql://u:p@elsewhere/db"

    def test_an_empty_database_url_falls_through_to_db_star(self, monkeypatch) -> None:
        """`DATABASE_URL=` with nothing after it is how "unset" is spelled in a
        compose file or a `.env`. Taking it as an answer would resolve to
        nothing while five `DB_*` variables sat right there."""
        _set(monkeypatch, **DB_ENV, DATABASE_URL="")

        assert resolve_database_url() == (
            "postgresql+psycopg://maistro:s3cret@db.internal:5433/maistro_prod"
        )

    @pytest.mark.parametrize("field", list(DB_ENV))
    def test_any_single_db_variable_counts_as_configured(self, monkeypatch, field: str) -> None:
        """Presence is read off the environment rather than by comparing
        `DatabaseSettings` to its defaults: every field has one, so a deployment
        that deliberately set `DB_USER=maistro` would look identical to one that
        set nothing at all."""
        _set(monkeypatch, **{field: DB_ENV[field]})

        assert resolve_database_url().startswith("postgresql+psycopg://")

    def test_nothing_configured_resolves_to_empty(self) -> None:
        """Not an error here. The container may legitimately run with no
        database — it warns and uses in-memory stores. Only callers that cannot
        proceed raise, and that is `require_database_url`'s job."""
        assert resolve_database_url() == ""

    def test_a_non_postgres_url_passes_through_untouched(self, monkeypatch) -> None:
        _set(monkeypatch, DATABASE_URL="sqlite:///var/lib/maistro.db")

        assert resolve_database_url() == "sqlite:///var/lib/maistro.db"

    def test_an_explicit_mapping_is_used_instead_of_the_process_environment(
        self, monkeypatch
    ) -> None:
        """The `env` parameter exists so a caller can resolve against something
        other than `os.environ` without mutating it."""
        _set(monkeypatch, DATABASE_URL="postgresql://from-process/db")

        assert resolve_database_url({"DATABASE_URL": "postgresql://from-arg/db"}) == (
            "postgresql://from-arg/db"
        )


class TestRequireIsStricterThanResolve:
    def test_no_database_is_an_error_rather_than_a_guessed_localhost(self) -> None:
        """`DatabaseSettings` defaults every field, so before this an empty
        environment silently pointed alembic at
        `postgresql://maistro:maistro@localhost:5432/maistro` — turning "you did
        not configure a database" into "connection refused to a host you never
        named"."""
        with pytest.raises(ConfigError) as caught:
            require_database_url()

        message = str(caught.value)
        assert "DATABASE_URL" in message
        assert "DB_HOST" in message, "and the other spelling that would work"

    @pytest.mark.parametrize("url", ["memory://", "sqlite:///var/lib/maistro.db"])
    def test_a_runtime_only_scheme_cannot_be_migrated(self, monkeypatch, url: str) -> None:
        """Both are legitimate `database_url` values for the container and
        meaningless to a chain that writes JSONB and needs the `vector`
        extension."""
        _set(monkeypatch, DATABASE_URL=url)

        with pytest.raises(ConfigError, match="not a PostgreSQL URL"):
            require_database_url()

    def test_the_rejection_does_not_leak_the_password(self, monkeypatch) -> None:
        """This lands in an uncaught startup traceback, and the URL it names may
        carry credentials even when the scheme is wrong."""
        _set(monkeypatch, DATABASE_URL="mysql://root:hunter2@db/app")

        with pytest.raises(ConfigError) as caught:
            require_database_url()

        assert "hunter2" not in str(caught.value)

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://u:p@h/db",
            "postgres://u:p@h/db",
            "postgresql+asyncpg://u:p@h/db",
        ],
    )
    def test_every_postgres_spelling_is_migratable(self, monkeypatch, url: str) -> None:
        _set(monkeypatch, DATABASE_URL=url)

        assert require_database_url() == url


class TestSyncUrlConversion:
    def test_the_async_driver_suffix_becomes_the_sync_one(self) -> None:
        """Alembic drives a synchronous engine, which cannot load asyncpg: it
        raises `InvalidRequestError: The asyncio extension requires an async
        driver` rather than connecting. `DatabaseSettings` exposes both
        spellings, so either may reach `DATABASE_URL`."""
        assert to_sync_url("postgresql+asyncpg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"

    def test_a_bare_scheme_is_rewritten_rather_than_left_alone(self) -> None:
        """This used to assert the bare URL came back unchanged, and that was
        the bug wearing a test. `postgresql://` is not driver-neutral:
        SQLAlchemy resolves it to psycopg2, which is not in `uv.lock` and is
        not installed by `uv sync --locked`, so `create_engine` raises
        ModuleNotFoundError. psycopg 3 is the declared sync driver."""
        assert to_sync_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"

    def test_an_already_correct_url_is_a_fixed_point(self) -> None:
        assert to_sync_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"

    def test_only_the_scheme_is_rewritten(self) -> None:
        """A password or database name containing the literal suffix must not be
        mangled — the rewrite anchors on the scheme by position."""
        url = "postgresql+asyncpg://u:postgresql+asyncpg://@h/db"

        assert to_sync_url(url) == "postgresql+psycopg://u:postgresql+asyncpg://@h/db"


class TestTheSchemeIsNormalisedForWhicheverEngineLoadsIt:
    """Accepting a spelling and then failing to load it is worse than
    rejecting it — the failure lands at connect time, in a startup traceback,
    naming a dialect rather than a configuration mistake."""

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://u:p@h/db",
            "postgres://u:p@h/db",
            "postgresql+asyncpg://u:p@h/db",
            "postgresql+psycopg://u:p@h/db",
        ],
    )
    def test_every_accepted_spelling_becomes_loadable_by_the_sync_engine(self, url: str) -> None:
        """`postgres://` is the one that bit first: SQLAlchemy 2 removed that
        dialect alias, so alembic failed on dialect lookup before connecting —
        while `_MIGRATABLE_SCHEMES` and this suite both declared it migratable.

        The bare `postgresql://` is the same failure one step later: the
        dialect resolves, and then the DBAPI import does not."""
        assert to_sync_url(url) == "postgresql+psycopg://u:p@h/db"

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://u:p@h/db",
            "postgres://u:p@h/db",
            "postgresql+asyncpg://u:p@h/db",
            "postgresql+psycopg://u:p@h/db",
        ],
    )
    def test_every_accepted_spelling_becomes_loadable_by_the_async_engine(self, url: str) -> None:
        """`memory.store.get_engine` builds an `AsyncEngine`, which cannot
        drive psycopg2 — so a bare `postgresql://` raised there and the
        surrounding `except` turned a configured database into a silent
        `None`."""
        assert to_async_url(url) == "postgresql+asyncpg://u:p@h/db"

    @pytest.mark.parametrize("converter", [to_sync_url, to_async_url])
    def test_a_non_postgres_url_is_untouched(self, converter) -> None:
        """Neither function's job is inventing a driver for a backend that may
        not have one wired."""
        assert converter("sqlite:///var/lib/maistro.db") == "sqlite:///var/lib/maistro.db"
        assert converter("memory://") == "memory://"

    @pytest.mark.parametrize("converter", [to_sync_url, to_async_url])
    def test_only_the_scheme_is_rewritten(self, converter) -> None:
        """A password containing the literal scheme must not be mangled — the
        rewrite is anchored at position 0, not a substring replace."""
        rewritten = converter("postgresql://u:postgres://@h/db")

        assert rewritten.endswith("://u:postgres://@h/db")


class TestTheSuppliedMappingIsTheOneUsed:
    def test_db_fields_compose_from_the_argument_not_the_process_environment(
        self, monkeypatch
    ) -> None:
        """`env` documents itself as "resolve against this instead of
        `os.environ`". Detecting the supplied `DB_*` fields and then composing
        from `os.environ` answered about a different database entirely."""
        _set(
            monkeypatch,
            DB_HOST="ambient.example",
            DB_NAME="ambient_db",
            DB_USER="ambient",
            DB_PASSWORD="ambient-pw",
        )

        resolved = resolve_database_url(
            {
                "DB_HOST": "supplied.example",
                "DB_PORT": "6000",
                "DB_NAME": "supplied_db",
                "DB_USER": "supplied",
                "DB_PASSWORD": "supplied-pw",
            }
        )

        assert resolved == (
            "postgresql+psycopg://supplied:supplied-pw@supplied.example:6000/supplied_db"
        )
        assert "ambient" not in resolved


class TestAnEmptyValueIsStillAConfiguredValue:
    def test_a_passwordless_database_counts_as_configured(self, monkeypatch) -> None:
        """`DB_PASSWORD=` is how a deployment spells passwordless PostgreSQL.
        Reading it as unset sent alembic to "No database configured" while the
        environment had explicitly named the database to use.

        Only the empty variable is set, deliberately. An earlier version of
        this test also set `DB_HOST` and friends to real values, so a
        truthiness check passed on *those* and the empty-value bug survived
        the mutation — the case only bites when every configured `DB_*` is
        empty, which is exactly the "rely on the other defaults" deployment
        Codex described.
        """
        monkeypatch.setenv("DB_PASSWORD", "")

        resolved = resolve_database_url()

        assert resolved, "an explicitly-set variable is a configured database"
        assert resolved.startswith("postgresql+psycopg://")
        assert require_database_url() == resolved, "and it is migratable, not an error"

    def test_a_truly_empty_environment_still_resolves_to_nothing(self) -> None:
        """The counterweight: presence-based detection must not turn "no
        database configured" into a localhost guess."""
        assert resolve_database_url({}) == ""


class TestDatabaseSettingsNamesItsDriver:
    """Both URL spellings name a driver explicitly, and each names a different
    one on purpose.

    A bare `postgresql://` is not neutral: SQLAlchemy resolves it to psycopg2,
    which this project has never declared as a dependency, so
    `alembic upgrade head` — the schema-evolution path ADR-087 documents —
    died with ModuleNotFoundError on any clean install. The async side has the
    mirror-image failure: a synchronous driver under `AsyncEngine` raises
    `InvalidRequestError` at connect time rather than at configuration time.

    Neither property needs a server, so nothing here is a database test; they
    are string construction, and they were the only lines in this module that
    no test read.
    """

    def test_the_async_url_names_asyncpg(self) -> None:
        settings = DatabaseSettings(
            host="db.internal", port=6543, name="maistro_prod", user="svc", password="pw"
        )

        assert settings.url == "postgresql+asyncpg://svc:pw@db.internal:6543/maistro_prod"

    def test_the_sync_url_names_psycopg_rather_than_defaulting_to_psycopg2(self) -> None:
        settings = DatabaseSettings(
            host="db.internal", port=6543, name="maistro_prod", user="svc", password="pw"
        )

        assert settings.sync_url == "postgresql+psycopg://svc:pw@db.internal:6543/maistro_prod"
        assert not settings.sync_url.startswith("postgresql://"), (
            "a bare scheme is what reached for psycopg2 and broke alembic"
        )

    def test_the_two_spellings_differ_only_in_the_driver(self) -> None:
        """The host, port, database and credentials must be identical — a
        migration that runs against a different database from the one the app
        opens is worse than one that fails to run."""
        settings = DatabaseSettings(host="h", port=1234, name="n", user="u", password="p")

        assert settings.url.split("://", 1)[1] == settings.sync_url.split("://", 1)[1]

    def test_alembic_can_load_the_sync_url_as_written(self) -> None:
        """`to_sync_url` is the normaliser every other entry point goes
        through; `sync_url` must already be a fixed point of it, or the two
        paths into alembic disagree about the driver."""
        settings = DatabaseSettings()

        assert to_sync_url(settings.sync_url) == settings.sync_url
