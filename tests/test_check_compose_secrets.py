"""A tracked Compose file must not hand anyone a credential (#367).

`docker-compose.pm-poc.yml` shipped `API_KEYS=alice:changeme-alice,bob:changeme-bob`
next to `REQUIRE_AUTH=true`, so the overlay read as a ready-to-run authenticated
deployment whose keys are published in this repository. gitleaks and
detect-secrets both stayed quiet, because `changeme-alice` is shaped like a
placeholder — which is exactly what makes it usable and exactly what makes a
secret scanner the wrong instrument.

Every other tracked profile already used `${VAR:?message}`. This gate holds the
one file that departed from that to the convention the rest already follow.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-compose-secrets.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("_check_compose_secrets", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scan(check, text: str):
    return check.scan_text(text, path="docker-compose.test.yml")


class TestWhatIsACommittedCredential:
    def test_a_bare_literal_is_reported(self, check) -> None:
        """The shape #367 was filed for."""
        found = _scan(check, "      - API_KEYS=alice:changeme-alice,bob:changeme-bob")
        assert len(found) == 1
        assert "literal value committed" in found[0].why

    def test_a_non_empty_fallback_is_reported(self, check) -> None:
        """The worse half. A bare literal at least looks like one; this reads as
        parameterised and silently supplies the known value to anyone who sets
        nothing."""
        found = _scan(check, "      - MAISTRO_ROUTER_API_KEY=${API_KEYS:-alice:changeme-alice}")
        assert len(found) == 1
        assert "falls back to a non-empty default" in found[0].why

    def test_the_mapping_form_is_checked_too(self, check) -> None:
        """Compose accepts both `- NAME=value` and `NAME: value`, and the prod
        overlay uses the second. Checking only one would leave half the tracked
        profiles unscanned."""
        assert _scan(check, "      POSTGRES_PASSWORD: hunter2")

    def test_a_dash_default_without_colon_is_still_a_fallback(self, check) -> None:
        """`${VAR-value}` differs from `${VAR:-value}` only for the empty
        string; both supply a committed value when the variable is unset."""
        assert _scan(check, "      - DB_PASSWORD=${DB_PASSWORD-hunter2}")

    def test_the_report_never_prints_the_value(self, check) -> None:
        """Printing it into a CI log is the same exposure one more time."""
        found = _scan(check, "      - API_KEYS=alice:changeme-alice")
        rendered = check.render(found, 1)
        assert "changeme-alice" not in rendered
        assert "API_KEYS" in rendered


class TestWhatIsFine:
    def test_required_with_a_message_passes(self, check) -> None:
        """The convention every other tracked profile already follows: unset
        means the deployment refuses to start, rather than starting insecurely."""
        assert not _scan(check, "      - API_KEYS=${API_KEYS:?Run ./install.sh to generate}")

    def test_an_empty_default_passes(self, check) -> None:
        """Genuinely optional secrets — an unset provider key is not a
        credential, it is the absence of one."""
        assert not _scan(check, "      - LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY:-}")

    def test_a_plain_substitution_passes(self, check) -> None:
        assert not _scan(check, "      - GITHUB_WEBHOOK_SECRET=${GITHUB_WEBHOOK_SECRET}")

    def test_a_commented_line_is_documentation(self, check) -> None:
        """`.env.example`-style guidance inside a compose file is not a
        deployment, and flagging it would push people to delete the
        explanation rather than fix anything."""
        assert not _scan(check, "      # - MAISTRO_LLM_API_KEY=sk-your-key")

    def test_a_non_secret_literal_is_left_alone(self, check) -> None:
        """The gate is about credentials, not about parameterising every
        setting. `REQUIRE_AUTH=true` is a decision, not a secret."""
        assert not _scan(check, "      - REQUIRE_AUTH=true")
        assert not _scan(check, "      - CORS_ORIGINS=http://localhost:8101")

    def test_an_inline_comment_is_not_part_of_the_value(self, check) -> None:
        assert not _scan(check, "      - API_KEYS=${API_KEYS:-}   # set in .env")


class TestWhichNamesCount:
    @pytest.mark.parametrize(
        "name",
        [
            "DB_PASSWORD",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "LANGFUSE_SECRET_KEY",
            "GITHUB_WEBHOOK_SECRET",
            "ATLASSIAN_API_TOKEN",
            "OPENAI_API_KEY",
            "API_KEYS",
            "LITELLM_MASTER_KEY",
        ],
    )
    def test_credential_names_are_recognised(self, check, name) -> None:
        """Matched by whole `_`-delimited segment, so a variable this
        repository has not added yet is covered the day it appears, without
        `TOKEN` also claiming `MAX_TOKENS`."""
        assert check.is_secret_name(name)

    @pytest.mark.parametrize("name", ["REQUIRE_AUTH", "CORS_ORIGINS", "MAISTRO_POC_MODE", "PORT"])
    def test_ordinary_settings_are_not(self, check, name) -> None:
        assert not check.is_secret_name(name)


class TestAgainstTheRealTree:
    def test_the_pm_poc_overlay_is_scanned(self, check) -> None:
        """The file #367 is about. A glob that missed it would have looked
        correct throughout, since every other profile was already right."""
        scanned = {p.relative_to(ROOT).as_posix() for p in check.compose_files()}
        assert "docker-compose.pm-poc.yml" in scanned

    def test_the_base_and_prod_profiles_are_scanned(self, check) -> None:
        scanned = {p.relative_to(ROOT).as_posix() for p in check.compose_files()}
        assert "docker-compose.yml" in scanned
        assert "deploy/docker-compose.prod.yml" in scanned

    def test_the_current_tree_is_clean(self, check) -> None:
        assert check.scan() == []

    def test_no_tracked_compose_file_still_carries_the_known_credential(self, check) -> None:
        """Belt and braces, and independent of the gate's own parsing: the
        string itself is gone from every deployment profile. The file set comes
        from `compose_files` rather than a second hand-written glob here --
        keeping one such glob in the tests is what let the gate and its tests
        agree on a set that was missing two files."""
        for path in check.compose_files():
            assert "changeme" not in path.read_text(encoding="utf-8"), path

    def test_the_env_example_placeholder_is_not_usable(self) -> None:
        """`.env.example` is not a deployment profile, so the gate does not
        scan it — but copying its API_KEYS line must still not produce a
        working credential."""
        body = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "changeme" not in body


class TestTheCommandLine:
    def test_a_clean_tree_exits_zero(self, check) -> None:
        assert check.main([]) == 0

    def test_a_violation_exits_nonzero(self, check, tmp_path) -> None:
        (tmp_path / "docker-compose.yml").write_text(
            "services:\n  app:\n    environment:\n      - DB_PASSWORD=hunter2\n",
            encoding="utf-8",
        )
        assert check.main(["--root", str(tmp_path)]) == 1

    def test_the_clean_message_says_how_much_it_looked_at(self, check, capsys) -> None:
        """ "ok" with no denominator cannot be told from "ok, I scanned
        nothing"."""
        check.main([])
        assert "tracked Compose file(s)" in capsys.readouterr().out


class TestTheGateSeesEveryComposeFile:
    """The review finding that mattered most: the gate reported `ok: 6 tracked
    Compose file(s)` while the tree held 8, and one of the two it missed
    carried a committed fallback credential. A gate that answers "ok" about a
    set it chose too narrowly is worse than no gate, because the "ok" is what
    people read.
    """

    def test_it_finds_every_compose_file_in_the_tree(self, check) -> None:
        """Enumerated independently of the gate's own globs -- a test that
        reused them would have agreed with the bug."""
        expected = set()
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in check.EXCLUDED_PARTS for part in path.parts):
                continue
            name = path.name
            if (
                name.startswith("docker-compose")
                or name in ("compose.yml", "compose.yaml")
                or name.endswith((".compose.yml", ".compose.yaml"))
            ) and name.endswith((".yml", ".yaml")):
                expected.add(path.relative_to(ROOT).as_posix())
        found = {p.relative_to(ROOT).as_posix() for p in check.compose_files()}
        assert found == expected

    def test_a_nested_package_profile_is_scanned(self, check) -> None:
        """The specific file the hand-written directory list missed."""
        found = {p.relative_to(ROOT).as_posix() for p in check.compose_files()}
        assert "packages/maistro-canvas/frontend/docker-compose.yml" in found

    def test_a_file_below_an_unanticipated_directory_is_scanned(self, check, tmp_path) -> None:
        """Depth is not the property being tested -- being unanticipated is.
        The gate must not need a code change to cover a directory nobody
        thought of when it was written."""
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "docker-compose.yml").write_text(
            "services:\n  app:\n    environment:\n      - DB_PASSWORD=hunter2\n",
            encoding="utf-8",
        )
        assert check.main(["--root", str(tmp_path)]) == 1

    @pytest.mark.parametrize("excluded", ["node_modules", ".venv", "third_party"])
    def test_vendored_trees_are_still_skipped(self, check, tmp_path, excluded) -> None:
        """Recursing everywhere must not start reporting other people's
        fixtures, which nobody here can fix."""
        vendored = tmp_path / excluded / "pkg"
        vendored.mkdir(parents=True)
        (vendored / "docker-compose.yml").write_text(
            "services:\n  app:\n    environment:\n      - DB_PASSWORD=hunter2\n",
            encoding="utf-8",
        )
        assert check.main(["--root", str(tmp_path)]) == 0


class TestSpellingsThatUsedToSlipPast:
    """Four ways to commit a working credential that the first version of this
    gate read as fine. Each is a real Compose spelling, not a contrivance."""

    def test_a_quoted_list_entry_is_checked(self, check) -> None:
        """Compose accepts `- "API_KEYS=hunter2"` as a YAML scalar and reads it
        identically to the unquoted form. A pattern that required the name
        immediately after the dash skipped it silently."""
        found = _scan(check, '      - "API_KEYS=hunter2"')
        assert len(found) == 1
        assert "literal value committed" in found[0].why

    def test_a_single_quoted_list_entry_is_checked(self, check) -> None:
        assert len(_scan(check, "      - 'API_KEYS=hunter2'")) == 1

    def test_an_escaped_dollar_is_a_literal_not_a_substitution(self, check) -> None:
        """Compose reads `$$` as an escaped dollar: `$$hunter2` reaches the
        container as the literal `$hunter2`. Accepting every value starting
        with `$` as "parameterised" let that through."""
        found = _scan(check, "      - API_KEYS=$$hunter2")
        assert len(found) == 1
        assert "literal value committed" in found[0].why

    def test_a_password_in_a_connection_url_is_reported(self, check) -> None:
        """`DATABASE_URL` carries no credential marker in its name, so nothing
        keyed on the name would ever have looked at its value -- and the value
        hands out a password."""
        found = _scan(check, "      - DATABASE_URL=postgresql://mcp:hunter2@db:5432/app")
        assert len(found) == 1
        assert "userinfo" in found[0].why

    @pytest.mark.parametrize("name", ["DATABASE_URL", "REDIS_URI", "PG_DSN"])
    def test_every_url_shaped_name_is_read_for_userinfo(self, check, name) -> None:
        assert len(_scan(check, f"      - {name}=postgresql://mcp:hunter2@db:5432/app")) == 1

    def test_a_parameterised_url_password_passes(self, check) -> None:
        """What the base profile already does, and what this gate is asking
        people to do -- so it must not be reported."""
        assert (
            _scan(
                check,
                "      - DATABASE_URL=postgresql://mcp:${DB_PASSWORD:?set it}@db:5432/app",
            )
            == []
        )

    def test_a_url_with_no_userinfo_passes(self, check) -> None:
        assert _scan(check, "      - DATABASE_URL=postgresql://db:5432/app") == []

    def test_a_url_with_a_username_but_no_password_passes(self, check) -> None:
        """A username is not a credential, and refusing one would push people
        to write the URL some other way rather than to remove a secret."""
        assert _scan(check, "      - DATABASE_URL=postgresql://mcp@db:5432/app") == []

    def test_the_url_report_still_never_prints_the_value(self, check) -> None:
        """The URL branch is the one place a whole connection string was in
        hand, which makes it the easiest place to leak one into a CI log."""
        found = _scan(check, "      - DATABASE_URL=postgresql://mcp:hunter2@db:5432/app")
        assert "hunter2" not in check.render(found, 1)


class TestNamesThatUsedToBeFalsePositives:
    """A gate that fails CI on `MAX_TOKENS=4096` with "replace this with a
    secret substitution" teaches people to work around it, which costs more
    than the findings it makes are worth."""

    @pytest.mark.parametrize(
        "name", ["MAX_TOKENS", "TOKENIZERS_PARALLELISM", "MAX_TOKENS_PER_REQUEST", "KEYSTONE_URL"]
    )
    def test_an_ordinary_setting_whose_name_contains_a_marker_is_left_alone(
        self, check, name
    ) -> None:
        assert not check.is_secret_name(name)

    @pytest.mark.parametrize("name", ["API_KEY", "MASTER_KEY", "DB_PASSWORD", "SECRET_KEY"])
    def test_the_marker_as_a_whole_segment_still_counts(self, check, name) -> None:
        assert check.is_secret_name(name)

    def test_a_max_tokens_literal_does_not_fail_the_gate(self, check) -> None:
        assert _scan(check, "      - MAX_TOKENS=4096") == []

    @pytest.mark.parametrize("spelling", ["null", "Null", "NULL", "~"])
    def test_a_yaml_null_is_not_a_committed_credential(self, check, spelling) -> None:
        """A null removes a variable rather than supplying one, which is the
        opposite of committing a credential -- and it is the documented way to
        clear a secret an image otherwise provides."""
        assert _scan(check, f"      API_KEY: {spelling}") == []


class TestTheTwoProfilesThisPrFixed:
    """Asserted against the real files, not against the gate's parse of them,
    so a future regression in either shows up as a failing test here."""

    def test_the_canvas_frontend_password_is_required(self) -> None:
        body = (ROOT / "packages/maistro-canvas/frontend/docker-compose.yml").read_text(
            encoding="utf-8"
        )
        assert "mcp_local_dev" not in body
        assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in body

    def test_the_pm_poc_router_key_reads_the_token_not_the_key_list(self) -> None:
        """`install.sh` writes `MAISTRO_ACCESS_TOKEN=<token>` and
        `API_KEYS=["<token>"]`. Sending API_KEYS as the router's bearer
        credential presents the JSON array as the token, and every call gets
        401 -- so the overlay's `:?` made it refuse to start *and* not work
        when it did."""
        body = (ROOT / "docker-compose.pm-poc.yml").read_text(encoding="utf-8")
        assert "MAISTRO_ROUTER_API_KEY=${MAISTRO_ACCESS_TOKEN:?" in body
        assert "MAISTRO_ROUTER_API_KEY=${API_KEYS" not in body

    def test_the_router_key_matches_what_the_base_profile_uses(self) -> None:
        """The overlay departed from a convention the base profile already
        had; the two must agree on which variable carries the token."""
        base = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "MAISTRO_ROUTER_API_KEY=${MAISTRO_ACCESS_TOKEN" in base
