"""Tests for the image build-context gate (#308).

The gate exists because `Dockerfile.rsi-runner` copies this repository into an
image that then executes agent-authored code, and nothing stopped `.env` from
riding along. So these are about the ways a secret could still get in: an
ignore rule that goes missing from one of the two files, a bare `COPY .`
returning, and — the subtler one — a rule so broad it strips source, because a
gate people have to disable to get a working image is a gate that gets
disabled.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-build-context.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_build_context", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bench(tmp_path: Path, gate, monkeypatch: pytest.MonkeyPatch):
    """Point the gate at ignore files and a Dockerfile we control."""

    def _set(
        root_text: str, runner_text: str, dockerfile: str = "", tracked: list[str] | None = None
    ):
        root = tmp_path / ".dockerignore"
        runner = tmp_path / "Dockerfile.rsi-runner.dockerignore"
        root.write_text(root_text, encoding="utf-8")
        runner.write_text(runner_text, encoding="utf-8")
        (tmp_path / "Dockerfile.rsi-runner").write_text(dockerfile, encoding="utf-8")
        monkeypatch.setattr(gate, "ROOT", tmp_path)
        monkeypatch.setattr(gate, "ROOT_IGNORE", root)
        monkeypatch.setattr(gate, "RUNNER_IGNORE", runner)
        monkeypatch.setattr(gate, "_tracked_paths", lambda: tracked or [])

    return _set


#: Enough to satisfy MUST_DENY, so a test can isolate the one thing it is about.
def _complete(gate) -> str:
    lines = [pattern for pattern, _why in gate.MUST_DENY]
    lines += sorted(gate.EXPECTED_NEGATIONS)
    return "\n".join(lines) + "\n"


class TestItReadsRulesRatherThanBytes:
    def test_comments_and_blank_lines_are_not_rules(self, gate) -> None:
        """The two files carry different headers on purpose — one explains the
        BuildKit split, the other explains being a copy — so a byte comparison
        would fail forever."""
        assert gate.rules("# a comment\n\n.env\n  \n.git\n") == [".env", ".git"]

    def test_indentation_does_not_make_a_new_rule(self, gate) -> None:
        assert gate.rules("  .env  \n") == [".env"]


class TestTheTwoFilesMustAgree:
    def test_identical_rules_pass(self, gate, bench) -> None:
        bench(_complete(gate), _complete(gate))

        assert gate.audit() == []

    def test_a_rule_in_only_one_file_fails(self, gate, bench) -> None:
        """BuildKit reads one and the classic builder the other, so a rule in
        one file is a protection that depends on which builder ran."""
        bench(_complete(gate), _complete(gate) + "extra-rule\n")

        failures = gate.audit()

        assert any("different rules" in message for message in failures)

    def test_a_different_header_alone_does_not_fail(self, gate, bench) -> None:
        bench("# root header\n" + _complete(gate), "# runner header\n" + _complete(gate))

        assert gate.audit() == []


class TestEverySecretPatternIsDenied:
    @pytest.mark.parametrize("index", range(9))
    def test_dropping_any_one_of_them_fails(self, gate, bench, index: int) -> None:
        if index >= len(gate.MUST_DENY):
            pytest.skip("MUST_DENY is shorter than this parametrisation")
        dropped = gate.MUST_DENY[index][0]
        text = "\n".join(line for line in _complete(gate).splitlines() if line != dropped) + "\n"
        bench(text, text)

        failures = gate.audit()

        assert any(repr(dropped) in message for message in failures)

    def test_env_example_stays_allowed(self, gate, bench) -> None:
        """`.env.example` is documentation with no value in it. A gate that
        demanded it be denied would be demanding the docs be removed."""
        text = "\n".join(pattern for pattern, _ in gate.MUST_DENY) + "\n"
        bench(text, text)

        assert any("env.example" in message for message in gate.audit())


class TestARuleMayNotStripSource:
    def test_a_rule_matching_a_tracked_file_fails(self, gate, bench) -> None:
        """`**/data/` is the natural rule to reach for and it would strip the
        Conductor's shipped dashboards and the BFCL corpus out of every image.
        Found in this PR's own first draft, by this check."""
        bench(
            _complete(gate) + "**/data/\n",
            _complete(gate) + "**/data/\n",
            tracked=["packages/hive-conductor/backend/data/deck_templates.json"],
        )

        failures = gate.audit()

        assert any("denies the TRACKED file" in message for message in failures)

    def test_a_negated_path_is_not_counted_as_stripped(self, gate, bench) -> None:
        """`.env.*` denies `.env.example` and `!.env.example` takes it back.
        Reading only the deny would report a file the build actually gets."""
        bench(_complete(gate), _complete(gate), tracked=[".env.example"])

        assert gate.audit() == []

    def test_an_untracked_secret_is_not_a_finding(self, gate, bench) -> None:
        """The point of the deny-list. `.env` is untracked, so denying it strips
        nothing from the build and everything from the risk."""
        bench(_complete(gate), _complete(gate), tracked=["pyproject.toml"])

        assert gate.audit() == []


class TestTheBareCopyCannotComeBack:
    def test_copy_dot_into_a_candidate_image_fails(self, gate, bench) -> None:
        bench(_complete(gate), _complete(gate), dockerfile="FROM x\nCOPY . /workspace\n")

        failures = gate.audit()

        assert any("copies the whole context" in message for message in failures)

    def test_an_explicit_allowlist_passes(self, gate, bench, tmp_path: Path) -> None:
        (tmp_path / "packages").mkdir()
        bench(
            _complete(gate),
            _complete(gate),
            dockerfile="FROM x\nCOPY packages /workspace/packages\n",
        )

        assert gate.audit() == []

    def test_a_copy_from_another_stage_is_not_a_context_copy(self, gate, bench) -> None:
        """`COPY --from=...` takes from an image, not from the build context,
        so it cannot carry the operator's `.env`."""
        bench(
            _complete(gate),
            _complete(gate),
            dockerfile="FROM x\nCOPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv\n",
        )

        assert gate.audit() == []

    def test_a_copy_source_that_does_not_exist_fails_here_not_in_the_build(
        self, gate, bench
    ) -> None:
        bench(
            _complete(gate),
            _complete(gate),
            dockerfile="FROM x\nCOPY not-a-real-directory /workspace/x\n",
        )

        assert any("does not exist" in message for message in gate.audit())


class TestTheRepositorysOwnBuildContext:
    def test_it_passes(self, gate) -> None:
        assert gate.audit() == []

    def test_the_runner_dockerfile_names_what_it_needs(self, gate) -> None:
        """The allowlist has to actually cover the loop's inputs: the packages,
        the lockfile it syncs from, and the docs `spec_tracker` scores against.
        """
        text = (ROOT / "Dockerfile.rsi-runner").read_text(encoding="utf-8")

        for needed in ("packages", "uv.lock", "pyproject.toml", "docs", "tests", "scripts"):
            assert needed in text, needed

    def test_both_ignore_files_are_tracked(self, gate) -> None:
        """An untracked `.dockerignore` protects the machine it was written on
        and no other."""
        tracked = set(gate._tracked_paths())

        assert ".dockerignore" in tracked
        assert "Dockerfile.rsi-runner.dockerignore" in tracked

    def test_main_passes_and_says_what_it_checked(self, gate, capsys) -> None:
        assert gate.main() == 0
        assert "secret pattern(s)" in capsys.readouterr().out

    def test_main_fails_and_names_the_problem(self, gate, bench, capsys) -> None:
        bench("", "")

        assert gate.main() == 1
        assert "does not deny" in capsys.readouterr().out
