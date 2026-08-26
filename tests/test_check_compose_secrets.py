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
        """Substring matching on purpose, so a variable this repository has not
        added yet is covered the day it appears."""
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

    def test_no_tracked_compose_file_still_carries_the_known_credential(self) -> None:
        """Belt and braces, and independent of the gate's own parsing: the
        string itself is gone from every deployment profile."""
        for path in ROOT.glob("**/docker-compose*.yml"):
            if any(part in ("node_modules", ".venv", ".git") for part in path.parts):
                continue
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
