"""A connection default must not carry a literal password (#432).

`packages/maistro-canvas/frontend` shipped the same credential-bearing URL in
`server/models/db.py` and `alembic.ini`, for a PostgreSQL container whose port
its Compose profile publishes to the host. `check-compose-secrets.py` (#367)
holds the same rule for Compose files and cannot read either of those shapes.

These tests are mostly about what the gate must *not* report. The repository is
full of `user:pass@host` strings that are entirely legitimate -- redaction
tests, docstrings describing a format, the text of an error telling an operator
what to set -- and a gate that flags those is one people learn to route around.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-connection-credentials.py"

#: The exact pair #432 was filed for.
SHIPPED_URL = "postgresql+asyncpg://mcp:mcp@localhost:5441/mcp_orders"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("_check_connection_credentials", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _py(check, text: str):
    return check.scan_python(Path("server/models/db.py"), text)


def _ini(check, text: str):
    return check.scan_ini(Path("alembic.ini"), text)


class TestTheShapesThisWasFiledFor:
    def test_an_environment_fallback_is_reported(self, check) -> None:
        found = _py(check, f'import os\nURL = os.environ.get("DATABASE_URL", "{SHIPPED_URL}")\n')
        assert len(found) == 1
        assert found[0].where == "environment default"

    def test_getenv_spelling_is_reported_too(self, check) -> None:
        """`os.getenv(name, default)` is the same fallback with another name."""
        found = _py(check, f'import os\nURL = os.getenv("DATABASE_URL", "{SHIPPED_URL}")\n')
        assert len(found) == 1

    def test_the_keyword_default_is_reported(self, check) -> None:
        """`default=` is positional-argument two spelled out."""
        found = _py(check, f'd.get("DATABASE_URL", default="{SHIPPED_URL}")\n')
        assert len(found) == 1

    def test_a_url_named_assignment_is_reported(self, check) -> None:
        found = _py(check, f'SQLALCHEMY_DATABASE_URI = "{SHIPPED_URL}"\n')
        assert len(found) == 1
        assert "SQLALCHEMY_DATABASE_URI" in found[0].where

    def test_an_annotated_assignment_is_reported(self, check) -> None:
        """`URL: str = "..."` is the same declaration with a type on it."""
        found = _py(check, f'DATABASE_DSN: str = "{SHIPPED_URL}"\n')
        assert len(found) == 1

    def test_the_ini_key_is_reported(self, check) -> None:
        found = _ini(check, f"[alembic]\nsqlalchemy.url = {SHIPPED_URL}\n")
        assert len(found) == 1
        assert found[0].line_no == 2


class TestWhatIsTextAboutAUrlRatherThanAUrl:
    def test_a_docstring_is_not_reported(self, check) -> None:
        assert _py(check, f'"""Falls back to {SHIPPED_URL} today."""\n') == []

    def test_a_comment_is_not_reported(self, check) -> None:
        assert _py(check, f"# was {SHIPPED_URL}\nX = 1\n") == []

    def test_an_error_message_is_not_reported(self, check) -> None:
        """`maistro.config.database` raises exactly this, and it is not a default."""
        text = 'MSG = "Set DATABASE_URL to a postgresql://user:pass@host/db URL"\n'
        assert _py(check, text) == []

    def test_a_non_url_name_is_not_reported(self, check) -> None:
        """`URL` must be the name's tail, not a substring: `URLLIB_TIMEOUT` is not a DSN."""
        assert _py(check, f'URLLIB_FALLBACK = "{SHIPPED_URL}"\n') == []

    def test_a_call_that_is_not_an_env_read_is_not_reported(self, check) -> None:
        assert _py(check, f'connect("{SHIPPED_URL}")\n') == []


class TestWhatCountsAsConfigured:
    def test_an_interpolated_ini_value_is_not_reported(self, check) -> None:
        assert _ini(check, "[alembic]\nsqlalchemy.url = ${DATABASE_URL}\n") == []

    def test_configparser_interpolation_is_not_reported(self, check) -> None:
        assert _ini(check, "[alembic]\nsqlalchemy.url = %(base_url)s\n") == []

    def test_a_url_without_a_password_is_not_reported(self, check) -> None:
        """No userinfo, nothing handed out."""
        assert _ini(check, "[alembic]\nsqlalchemy.url = postgresql://localhost/db\n") == []

    def test_a_commented_ini_line_is_not_reported(self, check) -> None:
        assert _ini(check, f"[alembic]\n# sqlalchemy.url = {SHIPPED_URL}\n") == []

    def test_a_path_that_looks_like_userinfo_is_not_reported(self, check) -> None:
        """`https://host/a:b@c` is a path segment; the userinfo is before the first `/`."""
        assert _py(check, 'DOC_URL = "https://example.com/a:b@c"\n') == []


class TestTheRepositoryItself:
    def test_no_tracked_source_carries_a_connection_credential(self, check) -> None:
        """The gate as CI runs it. This is what #432 closes."""
        findings, scanned = check.audit(ROOT)
        assert findings == [], [f"{f.path}:{f.line_no} {f.why}" for f in findings]
        assert scanned > 0

    def test_a_syntactically_broken_python_file_is_skipped(self, check) -> None:
        """A parse failure is `ruff`'s finding to report, not this gate's."""
        assert _py(check, "def (\n") == []


class TestTheCommandLine:
    def test_a_clean_tree_exits_zero_and_says_what_it_scanned(
        self, check, tmp_path, capsys
    ) -> None:
        (tmp_path / "ok.py").write_text('URL = os.environ.get("DATABASE_URL")\n')
        assert check.main([str(tmp_path)]) == 0
        assert "no connection default carries a literal credential" in capsys.readouterr().out

    def test_a_finding_exits_one_and_names_the_file_and_line(self, check, tmp_path, capsys) -> None:
        (tmp_path / "db.py").write_text(f'URL = os.environ.get("D", "{SHIPPED_URL}")\n')
        assert check.main([str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "db.py:1" in out
        assert "environment default" in out
        assert "server/config.py" in out, "the message must point at the shape to copy"

    def test_a_file_that_cannot_be_decoded_is_skipped(self, check, tmp_path) -> None:
        """A binary blob with a `.py` name is not this gate's finding to report."""
        (tmp_path / "blob.py").write_bytes(b"\xff\xfe\x00 not utf-8")
        findings, scanned = check.audit(tmp_path)
        assert findings == []
        assert scanned == 1

    def test_excluded_directories_are_not_scanned(self, check, tmp_path) -> None:
        """Vendored code and test fixtures are full of example credentials."""
        vendored = tmp_path / "node_modules"
        vendored.mkdir()
        (vendored / "db.py").write_text(f'DATABASE_URL = "{SHIPPED_URL}"\n')
        findings, scanned = check.audit(tmp_path)
        assert findings == []
        assert scanned == 0


class TestTheCanvasFrontendConfig:
    """`server/config.py` is what replaced the two literals (#432).

    It sits outside every measured coverage root and outside the mypy set, so
    without this it would be the one part of the fix nothing in CI executes --
    which is the position the code it replaced was in.
    """

    @pytest.fixture(scope="class")
    def config(self):
        path = ROOT / "packages" / "maistro-canvas" / "frontend" / "server" / "config.py"
        spec = importlib.util.spec_from_file_location("_canvas_frontend_config", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_database_url_wins_outright(self, config) -> None:
        env = {"DATABASE_URL": "postgresql+asyncpg://a:b@elsewhere/db", "POSTGRES_PASSWORD": "pw"}
        assert config.resolve_database_url(env) == "postgresql+asyncpg://a:b@elsewhere/db"

    def test_the_password_composes_the_compose_profiles_url(self, config) -> None:
        """The user, database and host port are what `docker-compose.yml` fixes."""
        composed = config.resolve_database_url({"POSTGRES_PASSWORD": "s3cret"})
        assert composed == "postgresql+asyncpg://mcp:s3cret@localhost:5441/mcp_orders"

    def test_a_whitespace_only_value_counts_as_unset(self, config) -> None:
        """`DATABASE_URL=` in a `.env` is how "unset" is usually spelled."""
        assert config.resolve_database_url({"DATABASE_URL": "   "}) == ""
        assert config.resolve_database_url({"POSTGRES_PASSWORD": "\t"}) == ""

    def test_nothing_configured_resolves_empty(self, config) -> None:
        assert config.resolve_database_url({}) == ""

    def test_requiring_an_unconfigured_database_raises_with_both_settings(self, config) -> None:
        with pytest.raises(config.ConfigError) as excinfo:
            config.require_database_url({})
        message = str(excinfo.value)
        assert "POSTGRES_PASSWORD" in message
        assert "DATABASE_URL" in message

    def test_requiring_a_configured_database_returns_it(self, config) -> None:
        assert config.require_database_url({"POSTGRES_PASSWORD": "pw"}).endswith("/mcp_orders")

    def test_the_composed_url_carries_no_default_password(self, config) -> None:
        """The regression #432 is about: no password anyone had to not supply."""
        assert "mcp:mcp@" not in config.resolve_database_url({"POSTGRES_PASSWORD": "pw"})
