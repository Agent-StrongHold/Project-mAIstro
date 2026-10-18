"""Tests for scripts/check-install-functions.py (#807 AC-4).

The gate exists because shellcheck cannot see calls to undefined functions
(it assumes sourced content it cannot see), and because the one installer
branch no Linux gate executes — the non-default Docker-socket path — is
exactly where the undefined `upsert_env` call shipped. These tests pin both
halves: the extraction's command-position shapes on synthetic sources, and
the real installers staying clean, including a replay of the original defect.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-install-functions.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_install_functions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _offender_names(gate, source: str) -> list[str]:
    return [word for word, _ in gate.undefined_invocations(source)]


class TestTheRealInstallers:
    def test_the_supported_entry_points_are_the_default_targets(self, gate) -> None:
        assert gate.DEFAULT_TARGETS == ("install.sh", "get.sh")
        for name in gate.DEFAULT_TARGETS:
            assert (ROOT / name).is_file(), f"{name} went missing"

    @pytest.mark.parametrize("name", ["install.sh", "get.sh"])
    def test_entry_points_define_every_function_they_invoke(self, gate, name: str) -> None:
        source = (ROOT / name).read_text(encoding="utf-8")
        assert gate.undefined_invocations(source) == []

    def test_the_shipped_defect_fails_the_gate(self, gate) -> None:
        """Replay #807: plant `upsert_env` back into the real install.sh at
        the same call site and the gate must name it."""
        source = (ROOT / "install.sh").read_text(encoding="utf-8")
        broken = source.replace(
            "set_env_value MAISTRO_DOCKER_SOCK", "upsert_env MAISTRO_DOCKER_SOCK"
        )
        assert broken != source, "the fixed call site disappeared"
        offenders = gate.undefined_invocations(broken)
        assert [word for word, _ in offenders] == ["upsert_env"]


class TestExtractionShapes:
    def test_a_typoed_helper_is_flagged_with_its_line(self, gate) -> None:
        source = "set_env_value() { :; }\nrecord() { upsert_env K V; }\n"
        assert gate.undefined_invocations(source) == [("upsert_env", 2)]

    def test_command_substitution_contents_are_commands(self, gate) -> None:
        source = 'path="$(mystery_helper arg)"\n'
        assert _offender_names(gate, source) == ["mystery_helper"]

    def test_process_substitution_contents_are_commands(self, gate) -> None:
        source = "source <(mystery_helper arg)\n"
        assert _offender_names(gate, source) == ["mystery_helper"]

    def test_quoted_prose_is_not_a_command_list(self, gate) -> None:
        """The original defect hid among shapes like this: parens inside
        message strings must not read as commands or word lists."""
        source = 'fail() { exit 1; }\nfail "Docker Engine 25+ (API 1.44+) required (not v29)."\n'
        assert gate.undefined_invocations(source) == []

    def test_case_patterns_are_data_but_branch_bodies_are_shell(self, gate) -> None:
        source = 'case "$host" in\n    Darwin) run_colima ;;\n    "*)") echo odd ;;\nesac\n'
        assert _offender_names(gate, source) == ["run_colima"]

    def test_variable_command_its_arguments_are_not_commands(self, gate) -> None:
        """`"${UV_CMD[@]}" tool install`: the command word is the expansion
        (not statically checkable) and `tool` is its argument."""
        source = 'UV_CMD=(uv)\n"${UV_CMD[@]}" tool install pkg\n'
        assert gate.undefined_invocations(source) == []

    def test_array_literals_are_data(self, gate) -> None:
        source = 'COMPOSE_UP_ARGS=(up -d)\nargs+=(--with "$x")\n'
        assert gate.undefined_invocations(source) == []

    def test_heredoc_bodies_are_not_shell(self, gate) -> None:
        source = "ok() { :; }\ncat <<'PY'\nimport sys\nmystery_helper()\nPY\nok done\n"
        assert gate.undefined_invocations(source) == []

    def test_backslash_continuations_stay_one_logical_line(self, gate) -> None:
        source = 'for key in A B \\\n    C D; do\n    handle "$key"\ndone\n'
        assert _offender_names(gate, source) == ["handle"]

    def test_arithmetic_is_not_commands(self, gate) -> None:
        source = "n=0\nn=$((n + 1))\n(( n > 0 )) && return\n"
        assert gate.undefined_invocations(source) == []

    def test_parameter_expansion_names_are_not_commands(self, gate) -> None:
        source = 'echo "${TAG:-latest}"\ngrep -qE "^${key}=" "$ENV_FILE"\n'
        assert gate.undefined_invocations(source) == []

    def test_a_substitution_inside_an_expansion_is_checked(self, gate) -> None:
        source = 'tag="${TAG:-$(mystery_helper)}"\n'
        assert _offender_names(gate, source) == ["mystery_helper"]

    def test_shell_programs_inside_quotes_are_not_commands(self, gate) -> None:
        source = "slug=\"$(printf '%s\\n' \"$x\" | sed -nE 's|a|b|p')\"\n"
        assert gate.undefined_invocations(source) == []

    def test_defined_and_builtin_calls_pass(self, gate) -> None:
        source = "start() { set -euo pipefail; docker info >/dev/null; }\nstart\n"
        assert gate.undefined_invocations(source) == []


class TestTheGateContract:
    def test_allowlist_entries_carry_justifications(self, gate) -> None:
        """Every externally-invoked command is a reviewed decision; an entry
        without a stated reason would let a dependency sneak in unowned."""
        assert gate.EXTERNAL_COMMANDS, "the allowlist must not be empty"
        for name, reason in gate.EXTERNAL_COMMANDS.items():
            assert isinstance(reason, str) and len(reason) >= 10, (
                f"EXTERNAL_COMMANDS[{name!r}] needs a justification"
            )

    def test_default_run_passes_on_this_repository(self, gate, capsys) -> None:
        assert gate.main([]) == 0
        assert "undefined invocation" not in capsys.readouterr().err

    def test_main_reports_and_exits_nonzero_on_a_offender(self, gate, tmp_path, capsys) -> None:
        fixture = tmp_path / "broken.sh"
        fixture.write_text("ok() { :; }\nupsert_env K V\n", encoding="utf-8")
        assert gate.main([str(fixture)]) == 1
        err = capsys.readouterr().err
        assert "upsert_env" in err
        assert "broken.sh:2" in err

    def test_main_fails_loudly_on_a_missing_target(self, gate, tmp_path, capsys) -> None:
        assert gate.main([str(tmp_path / "absent.sh")]) == 1
        assert "does not exist" in capsys.readouterr().err
