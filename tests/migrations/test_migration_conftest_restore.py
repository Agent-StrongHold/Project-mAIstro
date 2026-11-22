"""The migration conftest restores the service only where the chain can apply.

`pytest_sessionfinish` re-applies Alembic head so suites that follow the
migration tests against the same service start from a real schema. That
restore walks the chain from 001, and 001 opens with ``CREATE EXTENSION
vector`` — so on the `durable-events` job's plain ``postgres:17`` service the
restore could never succeed, and run 37472873061 failed that job through
``pytest.fail`` at session finish even though every test in the session had
passed. The hook now skips servers where 001's first statement cannot run.

These tests pin the halves of that contract: no restore where the chain
cannot apply, a loud failure where a capable server still cannot reach head,
and a probe that leaves a capable server exactly as it found it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from tests.migrations import conftest as restore

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRATCH_DB = "maistro_restore_probe_test"


def _finish(monkeypatch: pytest.MonkeyPatch, *, applicable: bool) -> list[str]:
    """Run the hook with the restore machinery replaced by recorders."""
    import psycopg

    calls: list[str] = []
    monkeypatch.setattr(restore, "_DATABASE_URL", "postgresql://probe.invalid/db")
    if applicable:
        monkeypatch.setattr(restore, "_chain_can_apply", lambda url: True)
    else:
        # Classify exactly the way the probe does: a psycopg failure means
        # "cannot apply". An unreachable URL is the reproducible stand-in for
        # the extension-less server — both are psycopg.Error at the probe.
        def refuse(url: str) -> bool:
            try:
                with psycopg.connect(url) as connection:
                    connection.execute(restore._FIRST_CHAIN_STATEMENT)
                    connection.rollback()
            except psycopg.Error:
                return False
            return True

        monkeypatch.setattr(restore, "_chain_can_apply", refuse)
    monkeypatch.setattr(restore, "_drop_public_tables", lambda: calls.append("drop"))
    monkeypatch.setattr(restore.subprocess, "run", lambda *args, **kwargs: calls.append("alembic"))
    restore.pytest_sessionfinish(session=None, exitstatus=0)  # type: ignore[arg-type]
    return calls


class TestTheSkipContract:
    def test_a_server_where_the_chain_cannot_apply_is_not_restored(self, monkeypatch):
        assert _finish(monkeypatch, applicable=False) == []

    def test_no_database_url_still_restores_nothing(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(restore, "_DATABASE_URL", "")
        monkeypatch.setattr(restore, "_chain_can_apply", lambda url: calls.append("probe"))
        monkeypatch.setattr(restore, "_drop_public_tables", lambda: calls.append("drop"))
        monkeypatch.setattr(
            restore.subprocess, "run", lambda *args, **kwargs: calls.append("alembic")
        )

        restore.pytest_sessionfinish(session=None, exitstatus=0)  # type: ignore[arg-type]

        assert calls == [], "without a URL there is no service to restore"


class TestTheLoudContract:
    def test_a_failed_upgrade_fails_the_session(self, monkeypatch):
        drop_calls: list[str] = []
        run_calls: list[list[str]] = []
        monkeypatch.setattr(restore, "_DATABASE_URL", "postgresql://probe.invalid/db")
        monkeypatch.setattr(restore, "_chain_can_apply", lambda url: True)
        monkeypatch.setattr(restore, "_drop_public_tables", lambda: drop_calls.append("drop"))

        def fake_run(argv, **kwargs):
            run_calls.append(argv)
            return SimpleNamespace(returncode=1, stderr="boom: relation does not exist")

        monkeypatch.setattr(restore.subprocess, "run", fake_run)

        with pytest.raises(pytest.fail.Exception) as excinfo:
            restore.pytest_sessionfinish(session=None, exitstatus=0)  # type: ignore[arg-type]

        assert "boom: relation does not exist" in str(excinfo.value)
        assert drop_calls == ["drop"], "tables are dropped before the head upgrade"
        assert run_calls == [[sys.executable, "-m", "alembic", "upgrade", "head"]]


class TestTheProbe:
    def test_revision_001_still_opens_with_the_probed_statement(self) -> None:
        """The probe executes 001's first statement by name. If the chain's
        first prerequisite ever changes, this pins the coupling so the probe
        is revisited instead of silently probing a stale statement."""
        source = (REPO_ROOT / "alembic" / "versions" / "001_initial_memory_schema.py").read_text(
            encoding="utf-8"
        )
        assert restore._FIRST_CHAIN_STATEMENT in source


@pytest.mark.skipif(
    not DATABASE_URL, reason="MAISTRO_TEST_DATABASE_URL is unset; the probe needs a server"
)
class TestAgainstAServer:
    @pytest.fixture(autouse=True)
    def _capable_server(self):
        """These cases classify a *capable* server. Run against a plain
        postgres:17 (no pgvector) they would fail for the very reason the
        hook now skips there — the same convention test_memory_embeddings
        documents for its pgvector-dependent legs."""
        if not restore._chain_can_apply(DATABASE_URL):
            pytest.skip("the configured server cannot apply revision 001 (no pgvector)")
        yield

    def _scratch_url(self) -> str:
        return urlsplit(DATABASE_URL)._replace(path=f"/{SCRATCH_DB}").geturl()

    def _admin_url(self) -> str:
        return urlsplit(DATABASE_URL)._replace(path="/postgres").geturl()

    def test_a_capable_server_is_classified_as_applicable(self) -> None:
        assert restore._chain_can_apply(DATABASE_URL) is True

    def test_the_probe_creates_nothing_on_a_fresh_database(self) -> None:
        """The probe runs 001's first statement inside a rolled-back
        transaction, so even on a server where it succeeds the database it
        probed is left without the extension."""
        import psycopg

        with psycopg.connect(self._admin_url(), autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
            connection.execute(f'CREATE DATABASE "{SCRATCH_DB}" TEMPLATE template0')
        try:
            assert restore._chain_can_apply(self._scratch_url()) is True
            with psycopg.connect(self._scratch_url()) as connection:
                installed = connection.execute(
                    "select 1 from pg_extension where extname = 'vector'"
                ).fetchone()
            assert installed is None, "the probe's rolled-back CREATE leaked"
        finally:
            with psycopg.connect(self._admin_url(), autocommit=True) as connection:
                connection.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
