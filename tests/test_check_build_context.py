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


#: Enough to satisfy the gate, so a test can isolate the one thing it is about.
#:
#: Ordered the way the real files are, because order is now part of what is
#: checked: an exception that re-includes a build output goes ABOVE the secret
#: denials, so nothing it re-includes can be a secret, and the `.env.example`
#: exception goes below the `.env` rules it is an exception to.
def _complete(gate) -> str:
    env_example = sorted(n for n in gate.EXPECTED_NEGATIONS if ".env.example" in n)
    lines = sorted(n for n in gate.EXPECTED_NEGATIONS if ".env.example" not in n)
    lines += [pattern for pattern, _why in gate.MUST_DENY]
    lines += env_example
    return "\n".join(lines) + "\n"


class TestItReadsRulesRatherThanBytes:
    def test_comments_and_blank_lines_are_not_rules(self, gate) -> None:
        """The two files carry different headers on purpose — one explains the
        BuildKit split, the other explains being a copy — so a byte comparison
        would fail forever."""
        assert gate.rules("# a comment\n\n.env\n  \n.git\n") == [".env", ".git"]

    def test_indentation_does_not_make_a_new_rule(self, gate) -> None:
        assert gate.rules("  .env  \n") == [".env"]


class TestTheMatcherIsDockersAndNotFnmatchs:
    """The gate's verdicts are only as good as its matcher (#510).

    `fnmatch` lets `*` cross a separator, so the previous matcher read
    `*.p12` as denying `packages/provider/client.p12` — the exact
    root-relative-pattern defect it was there to catch. The docstring called
    that a safe-side approximation; it was blindness in the unsafe direction.
    """

    @pytest.mark.parametrize(
        "rule,path,denied",
        [
            ("*.p12", "client.p12", True),
            ("*.p12", "packages/provider/client.p12", False),
            ("**/*.p12", "packages/provider/client.p12", True),
            ("**/*.p12", "client.p12", True),
            ("**/.env", ".env", True),
            ("**/.env", "a/b/c/.env", True),
            (".env", "a/.env", False),
            ("/secrets/", "secrets", True),
            ("/secrets/", "secrets/token", True),
            ("/secrets/", "packages/secrets/token", False),
            ("**/secrets/", "packages/provider/secrets/token", True),
            ("/vault/", "vault/master.age", True),
            ("/vault/", "packages/maistro-core/tests/vault/conftest.py", False),
            ("**/*.py[cod]", "packages/x/module.pyc", True),
            ("**/*.py[cod]", "packages/x/module.py", False),
            (
                "packages/hive-conductor/frontend/dist/**",
                "packages/hive-conductor/frontend/dist/a.js",
                True,
            ),
            ("id_rsa*", "id_rsa.pub", True),
            ("id_rsa*", "sub/id_rsa", False),
        ],
    )
    def test_it_matches_the_way_docker_does(self, gate, rule: str, path: str, denied: bool) -> None:
        assert gate.denies(rule, path) is denied


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


class TestAnExceptionCannotUndoADenial:
    """The finding: `MUST_DENY` asks whether a denial is written (#510).

    Docker resolves a path by the LAST rule that matches, so an exception
    written below the secret rules re-includes what they denied while every
    literal-presence check still passes. The gate now evaluates the finished
    rule set instead of reading it for keywords.
    """

    def test_an_exception_below_the_secret_rules_re_includes_a_secret(self, gate, bench) -> None:
        weakened = _complete(gate) + "!packages/hive-conductor/frontend/dist/**\n"
        bench(weakened, weakened)

        failures = gate.audit()

        assert any(
            "packages/hive-conductor/frontend/dist/.env" in message for message in failures
        ), failures

    def test_the_same_exception_above_them_is_fine(self, gate, bench) -> None:
        """Which is why the real files put the secret denials last."""
        bench(_complete(gate), _complete(gate))

        assert gate.audit() == []

    def test_an_exception_nobody_wrote_down_fails(self, gate, bench) -> None:
        """An exception is the only construct that can undo a denial, so the
        set of them is closed rather than merely reviewed."""
        weakened = "!packages/provider/.env\n" + _complete(gate)
        bench(weakened, weakened)

        assert any("unrecognised exception" in message for message in gate.audit())

    def test_every_expected_negation_carries_its_reason(self, gate) -> None:
        """The allowlist is prose a reader can weigh, not a bare set."""
        assert all(why.strip() for why in gate.EXPECTED_NEGATIONS.values())


class TestSecretsAreDeniedAtEveryDepth:
    """`*.p12` denies `client.p12` and not `packages/provider/client.p12`.

    Docker matches relative to the context root, and the runner copies the
    whole `packages` tree, so the recursive form is the one doing the work.
    Every private-key pattern was written in the root-relative form only, and
    `MUST_DENY` checked those same ineffective forms (Codex, #510).
    """

    @pytest.mark.parametrize(
        "recursive,probe",
        [
            ("**/*.p12", "packages/provider/client.p12"),
            ("**/*.pfx", "packages/provider/client.pfx"),
            ("**/id_rsa*", "packages/provider/id_rsa"),
            ("**/id_ed25519*", "packages/provider/id_ed25519"),
            ("**/.age-key*", "packages/provider/.age-key.txt"),
            ("**/recovery-phrase*", "packages/provider/recovery-phrase.txt"),
        ],
    )
    def test_dropping_the_recursive_form_lets_the_key_in(
        self, gate, bench, recursive: str, probe: str
    ) -> None:
        without = "\n".join(line for line in _complete(gate).splitlines() if line != recursive)
        bench(without + "\n", without + "\n")

        failures = gate.audit()

        assert any(probe in message for message in failures), failures

    def test_the_root_relative_form_alone_does_not_satisfy_the_probe(self, gate) -> None:
        """Stated directly, because it is the whole misreading: these two
        patterns look interchangeable and are not."""
        assert gate._is_denied(["id_rsa*"], "id_rsa")
        assert not gate._is_denied(["id_rsa*"], "packages/provider/id_rsa")
        assert gate._is_denied(["**/id_rsa*"], "packages/provider/id_rsa")


class TestTheBuildStillGetsWhatItNeeds:
    """A gate that only checked denials would be satisfied by denying everything."""

    def test_stripping_the_generated_bundle_fails(self, gate, bench) -> None:
        """The backend image's Dockerfile copies `frontend/dist/`, and this
        root file governs that build too — `**/dist` alone breaks it at COPY,
        after the base image and apt layer are already built (Codex, #510).
        """
        without_exception = "\n".join(
            line
            for line in (_complete(gate) + "**/dist\n").splitlines()
            if not line.startswith("!packages/hive-conductor/frontend/dist")
        )
        bench(without_exception + "\n", without_exception + "\n")

        failures = gate.audit()

        assert any("dist/index.js" in message for message in failures), failures

    def test_denying_the_documented_env_example_fails(self, gate, bench) -> None:
        without = "\n".join(
            line for line in _complete(gate).splitlines() if ".env.example" not in line
        )
        bench(without + "\n", without + "\n")

        assert any(".env.example" in message for message in gate.audit())


class TestARuleHereCanBreakABuildOverThere:
    """This file governs every `docker build` rooted at the repository (#510).

    `**/dist` was written for build output and took
    `packages/hive-conductor/frontend/dist/` out of the backend image's
    context, where its Dockerfile copies it. The gate read only the RSI
    runner's Dockerfile, so nothing noticed until a build log did.
    """

    def test_a_rule_that_excludes_another_dockerfiles_copy_source_fails(
        self, gate, bench, tmp_path: Path
    ) -> None:
        other = tmp_path / "packages" / "app"
        other.mkdir(parents=True)
        (other / "Dockerfile").write_text(
            "FROM x\nCOPY packages/app/dist/ /srv/\n", encoding="utf-8"
        )
        ignore = _complete(gate) + "**/dist\n"
        bench(
            ignore,
            ignore,
            dockerfile="FROM x\nCOPY packages /workspace/packages\n",
            tracked=["packages/app/Dockerfile"],
        )

        failures = gate.audit()

        assert any("would fail at that COPY" in message for message in failures), failures

    def test_the_same_dockerfile_passes_once_the_bundle_is_re_included(
        self, gate, bench, tmp_path: Path
    ) -> None:
        other = tmp_path / "packages" / "app"
        other.mkdir(parents=True)
        (other / "Dockerfile").write_text(
            "FROM x\nCOPY packages/app/dist/ /srv/\n", encoding="utf-8"
        )
        ignore = _complete(gate) + "**/dist\n!packages/app/dist\n"
        bench(ignore, ignore, tracked=["packages/app/Dockerfile"])

        # This one check, not the whole audit: `!packages/app/dist` is not in
        # EXPECTED_NEGATIONS, and being refused for that is a different test.
        assert gate._denied_copy_sources(gate.rules(ignore)) == []

    def test_the_real_repositorys_dockerfiles_all_get_what_they_copy(self, gate) -> None:
        """Run for real over every tracked Dockerfile, not a fixture: the
        finding was about a Dockerfile the gate had never looked at."""
        root_rules = gate.rules(gate.ROOT_IGNORE.read_text(encoding="utf-8"))

        assert gate._denied_copy_sources(root_rules) == []

    def test_it_looks_at_more_than_the_runner(self, gate) -> None:
        seen = gate._dockerfiles()

        assert "packages/hive-conductor/backend/Dockerfile" in seen
        assert "Dockerfile.rsi-runner" in seen
        assert not any(name.endswith(".dockerignore") for name in seen)

    def test_a_copy_from_an_earlier_stage_is_not_a_context_copy(self, gate, tmp_path: Path) -> None:
        """`COPY --from=` takes from an image, so no ignore rule applies."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM x\nCOPY --from=frontend /build/dist /app/dist\n", "utf-8")

        assert gate._copy_sources(dockerfile) == []


class TestTheRunnerImageCarriesTheFixturesItsTestsRead:
    """`tools/run_rsi_isolated.sh` scores every candidate against a baseline run
    of `packages/maistro-rsi/tests`. Two of those tests read repository fixtures
    directly, and neither tree was copied — so the baseline itself failed with
    `FileNotFoundError` and every candidate was rejected on its merits
    regardless of what it changed (Codex, #510).
    """

    DOCKERFILE = ROOT / "Dockerfile.rsi-runner"

    @pytest.mark.parametrize(
        "fixture,read_by",
        [
            ("sbx/maistro-rsi/spec.yaml", "packages/maistro-rsi/tests/test_sandbox.py"),
            (
                ".github/workflows/rsi-harvest.yml",
                "packages/maistro-rsi/tests/test_harvest_entry_point.py",
            ),
        ],
    )
    def test_the_fixture_exists_and_its_tree_is_copied(self, fixture: str, read_by: str) -> None:
        assert (ROOT / fixture).is_file(), f"{read_by} reads {fixture}"
        tree = fixture.split("/")[0]
        text = self.DOCKERFILE.read_text(encoding="utf-8")
        assert f"COPY {tree} /workspace/{tree}" in text, fixture

    def test_the_test_that_reads_it_still_does(self, gate) -> None:
        """Pinning the coupling, not just the file: if a test stops reading the
        fixture the COPY can go, and if it starts reading another one this test
        is where somebody finds out."""
        sandbox = (ROOT / "packages/maistro-rsi/tests/test_sandbox.py").read_text(encoding="utf-8")
        harvest = (ROOT / "packages/maistro-rsi/tests/test_harvest_entry_point.py").read_text(
            encoding="utf-8"
        )

        assert "sbx" in sandbox and "spec.yaml" in sandbox
        assert "rsi-harvest.yml" in harvest

    def test_gitignore_is_copied(self) -> None:
        """The image does `git add -A` on a fresh repo, and so does every
        candidate run. Without it a `.pytest_cache/` the agent's own test run
        produced is committed into the candidate and can ride out in a patch.
        """
        assert ".gitignore" in self.DOCKERFILE.read_text(encoding="utf-8")


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
