from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from maistro_server.entrypoint import _psycopg_dsn, _wait_for_migration_lock, run_migrations


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("postgresql://u:p@db/name", "postgresql://u:p@db/name"),
        ("postgres://u:p@db/name", "postgresql://u:p@db/name"),
        ("postgresql+asyncpg://u:p@db/name", "postgresql://u:p@db/name"),
        ("postgresql+psycopg://u:p@db/name", "postgresql://u:p@db/name"),
    ],
)
def test_psycopg_dsn_normalizes_supported_postgres_schemes(source: str, expected: str) -> None:
    assert _psycopg_dsn(source) == expected


def test_migration_lock_retries_until_acquired() -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.side_effect = [(False,), (True,)]

    with patch("maistro_server.entrypoint.time.sleep"):
        _wait_for_migration_lock(connection, timeout_s=1)

    assert connection.execute.call_count == 2


def test_migration_lock_times_out() -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (False,)

    with (
        patch("maistro_server.entrypoint.time.monotonic", side_effect=[0.0, 2.0]),
        pytest.raises(TimeoutError, match="migration lock"),
    ):
        _wait_for_migration_lock(connection, timeout_s=1, poll_s=0)


def test_run_migrations_holds_lock_until_upgrade_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (True,)
    context = Mock()
    context.__enter__ = Mock(return_value=connection)
    context.__exit__ = Mock(return_value=False)

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/name")
    with (
        patch("maistro_server.entrypoint.psycopg.connect", return_value=context) as connect,
        patch("maistro_server.entrypoint.command.upgrade") as upgrade,
    ):
        run_migrations()

    connect.assert_called_once_with("postgresql://u:p@db/name", autocommit=True)
    upgrade.assert_called_once()
    assert "pg_advisory_unlock" in connection.execute.call_args_list[-1].args[0]
