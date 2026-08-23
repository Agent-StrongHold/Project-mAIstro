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
    to_sync_url,
)
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
    """No inherited database configuration — these tests set their own."""
    for name in ("DATABASE_URL", *DB_ENV):
        monkeypatch.delenv(name, raising=False)


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
            "postgresql://maistro:s3cret@db.internal:5433/maistro_prod"
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

    def test_the_conductor_passes_a_resolved_url_to_the_container(self) -> None:
        """The last mile, and the one that made the rest academic.

        `hive-conductor`'s adapter constructed `AgentConfig(...)` without
        `database_url` at all, so it took the `""` default and the Conductor ran
        on in-memory stores regardless of what the deployment configured. Fixing
        the resolver without this would have left the shipped app exactly as
        broken, with a passing test suite.

        Structural for the same reason as the alembic guard: `backend/` is a
        flat application package outside `packages/*/src` and importing the
        adapter drags in the whole FastAPI app.
        """
        import ast
        from pathlib import Path

        adapter = (
            Path(__file__).resolve().parents[4]
            / "packages"
            / "hive-conductor"
            / "backend"
            / "adapters"
            / "maistro_core.py"
        )
        tree = ast.parse(adapter.read_text())

        agent_config_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "AgentConfig"
        ]
        assert agent_config_calls, "the adapter must still construct an AgentConfig"
        for call in agent_config_calls:
            passed = {kw.arg: kw.value for kw in call.keywords}
            assert "database_url" in passed, (
                "AgentConfig without database_url takes the ephemeral default"
            )
            value = passed["database_url"]
            assert isinstance(value, ast.Call), "and it must be resolved, not hardcoded"
            assert isinstance(value.func, ast.Name)
            assert value.func.id == "resolve_database_url"


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
            "postgresql://maistro:s3cret@db.internal:5433/maistro_prod"
        )

    @pytest.mark.parametrize("field", list(DB_ENV))
    def test_any_single_db_variable_counts_as_configured(self, monkeypatch, field: str) -> None:
        """Presence is read off the environment rather than by comparing
        `DatabaseSettings` to its defaults: every field has one, so a deployment
        that deliberately set `DB_USER=maistro` would look identical to one that
        set nothing at all."""
        _set(monkeypatch, **{field: DB_ENV[field]})

        assert resolve_database_url().startswith("postgresql://")

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
    def test_the_async_driver_suffix_is_stripped(self) -> None:
        """Alembic drives a synchronous engine, which cannot load asyncpg: it
        raises `InvalidRequestError: The asyncio extension requires an async
        driver` rather than connecting. `DatabaseSettings` exposes both
        spellings, so either may reach `DATABASE_URL`."""
        assert to_sync_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"

    def test_a_plain_url_is_unchanged(self) -> None:
        assert to_sync_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"

    def test_only_the_scheme_is_rewritten(self) -> None:
        """A password or database name containing the literal suffix must not be
        mangled — `replace(..., 1)` anchors on the scheme by position."""
        url = "postgresql+asyncpg://u:postgresql+asyncpg://@h/db"

        assert to_sync_url(url) == "postgresql://u:postgresql+asyncpg://@h/db"
