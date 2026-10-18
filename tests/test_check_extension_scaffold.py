"""The scaffold fixture's plan, in process (#973, #975, epic #945).

`scripts/check-extension-scaffold.py` is the physical acceptance: it builds
wheels, creates fresh venvs, installs exactly the developer tools into them,
and certifies — as its own CI step, minutes of subprocess work that a pytest
suite must not pay on every run.

What a suite CAN test in process is everything the physical run would
silently get wrong if it drifted:

- the pure logic (dist-name normalization, wheel discovery, policy loading,
  key generation, report public-key extraction);
- `_run`'s contract — including the negative controls, where a command
  *succeeding* is the violation;
- the exact command plan for a family round trip and the reference
  extension: the install list, the unimportable roots (and their neutral
  working directory), the staged sample tests, the certify/sign/verify
  sequence, and the mutated-byte negative control — asserted on recorded
  `Step`s with the subprocess boundary stubbed, the same shape
  `tests/test_check_reference_extension.py` pins for its fixture;
- `main`'s aggregation: every family by default, one with `--family`, a
  family failure skipping the reference leg, and the exit codes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCRIPT = ROOT / "scripts" / "check-extension-scaffold.py"
REAL_POLICY = ROOT / "extensions" / "namespace-policy.json"


@pytest.fixture(scope="module")
def fixture() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_extension_scaffold", FIXTURE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_extension_scaffold"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- pure logic


class TestCleanEnv:
    def test_the_levers_that_could_smuggle_the_repo_in_are_removed(
        self, fixture: types.ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PYTHONPATH", "/leak")
        monkeypatch.setenv("PYTHONHOME", "/leak-home")
        monkeypatch.setenv("KEEP_ME", "1")
        env = fixture.clean_env()
        assert "PYTHONPATH" not in env
        assert "PYTHONHOME" not in env
        assert env["KEEP_ME"] == "1"


class TestDistNameNormalization:
    def test_wheel_filenames_normalize_to_the_distribution_name(
        self, fixture: types.ModuleType
    ) -> None:
        assert fixture._normalize_dist_name("maistro-ext-sdk") == "maistro-ext-sdk"
        assert fixture._normalize_dist_name("Maistro_Ext.SDK") == "maistro-ext-sdk"
        assert fixture._normalize_dist_name("acme..widget--x") == "acme-widget-x"


class TestFindBuiltWheel:
    def test_the_single_matching_wheel_is_found_despite_case_and_underscores(
        self, fixture: types.ModuleType, tmp_path: Path
    ) -> None:
        (tmp_path / "Maistro_Ext.SDK-1.0.0-py3-none-any.whl").write_bytes(b"whl")
        (tmp_path / "maistro-ext-harness-1.0.0-py3-none-any.whl").write_bytes(b"other")
        found = fixture._find_built_wheel(tmp_path, "maistro-ext-sdk")
        assert found.name == "Maistro_Ext.SDK-1.0.0-py3-none-any.whl"

    @pytest.mark.parametrize("wheels", [(), ("a-1.0.whl", "b-1.0.whl")], ids=["none", "two"])
    def test_an_ambiguous_dist_is_a_fixture_error(
        self, fixture: types.ModuleType, tmp_path: Path, wheels: tuple[str, ...]
    ) -> None:
        for name in wheels:
            (tmp_path / name).write_bytes(b"w")
        with pytest.raises(fixture.FixtureError, match="exactly one"):
            fixture._find_built_wheel(tmp_path, "maistro-ext-sdk")


class TestRun:
    def test_a_succeeding_step_returns_its_stdout(self, fixture: types.ModuleType) -> None:
        out = fixture._run(fixture.Step("echo", (sys.executable, "-c", "print('hi')")))
        assert out.strip() == "hi"

    def test_a_failing_step_raises_with_the_command_and_streams(
        self, fixture: types.ModuleType
    ) -> None:
        step = fixture.Step("boom", (sys.executable, "-c", "print('out'); raise SystemExit(3)"))
        with pytest.raises(fixture.FixtureError, match=r"boom failed \(exit 3\)") as excinfo:
            fixture._run(step)
        message = str(excinfo.value)
        assert "raise SystemExit(3)" in message  # the command, for the CI log
        assert "out" in message and "stderr:" in message

    def test_a_negative_control_that_succeeds_is_the_violation(
        self, fixture: types.ModuleType
    ) -> None:
        step = fixture.Step(
            "must fail",
            (sys.executable, "-c", "print('regrettably fine')"),
            expect_failure=True,
        )
        with pytest.raises(fixture.FixtureError, match="succeeded where it must not"):
            fixture._run(step)

    def test_a_negative_control_that_fails_is_the_proof(self, fixture: types.ModuleType) -> None:
        step = fixture.Step(
            "must fail",
            (sys.executable, "-c", "print('declined'); raise SystemExit(1)"),
            expect_failure=True,
        )
        assert fixture._run(step).strip() == "declined"


class TestGenerateSigningKey:
    def test_the_seed_is_saved_and_the_publisher_key_returned(
        self,
        fixture: types.ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(fixture, "_run", lambda step: "11" * 32 + "\n" + "22" * 32 + "\n")
        key_file = tmp_path / "key.hex"
        publisher_key = fixture.generate_signing_key(tmp_path / "venv" / "python", key_file)
        assert publisher_key == "22" * 32
        assert key_file.read_text(encoding="utf-8") == "11" * 32

    def test_unexpected_generator_output_is_a_fixture_error(
        self, fixture: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(fixture, "_run", lambda step: "only-one-line\n")
        with pytest.raises(fixture.FixtureError, match="key-generator output"):
            fixture.generate_signing_key(tmp_path / "python", tmp_path / "key.hex")


class TestPublicKeyFromReport:
    def test_the_signed_report_carries_its_publisher_key(
        self, fixture: types.ModuleType, tmp_path: Path
    ) -> None:
        report = tmp_path / "r.json"
        report.write_text(
            json.dumps({"signature": {"signed": True, "public_key": "ab" * 32}}),
            encoding="utf-8",
        )
        assert fixture._public_key_from_report(report) == "ab" * 32

    @pytest.mark.parametrize(
        "document",
        [{"signature": {"signed": False, "reason": "no key"}}, {}],
        ids=["explicitly-unsigned", "no-signature-block"],
    )
    def test_an_unsigned_report_has_no_key_to_verify_against(
        self, fixture: types.ModuleType, tmp_path: Path, document: dict
    ) -> None:
        report = tmp_path / "r.json"
        report.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(fixture.FixtureError, match="no signature to verify"):
            fixture._public_key_from_report(report)


class TestLoadPolicy:
    def test_the_real_policy_names_product_private_roots(self, fixture: types.ModuleType) -> None:
        roots = fixture.load_policy(REAL_POLICY)
        assert "maistro_server" in roots
        assert all(isinstance(root, str) for root in roots)

    def test_a_policy_without_the_sdk_or_harness_forbids_them_too(
        self, fixture: types.ModuleType, tmp_path: Path
    ) -> None:
        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({"product_private_namespaces": ["maistro"]}), encoding="utf-8")
        assert fixture.load_policy(policy) == ("maistro",)

    def test_a_missing_policy_is_a_fixture_error(self, fixture: types.ModuleType) -> None:
        with pytest.raises(fixture.FixtureError, match="policy file not found"):
            fixture.load_policy(Path("/nonexistent/policy.json"))

    def test_an_invalid_policy_json_is_a_fixture_error(
        self, fixture: types.ModuleType, tmp_path: Path
    ) -> None:
        policy = tmp_path / "policy.json"
        policy.write_text("{not json", encoding="utf-8")
        with pytest.raises(fixture.FixtureError, match="not valid JSON"):
            fixture.load_policy(policy)

    @pytest.mark.parametrize(
        "raw",
        [["maistro"], ["maistro", 3], {"product_private_namespaces": "maistro"}],
        ids=["list-root", "items", "type"],
    )
    def test_a_malformed_roots_declaration_is_a_fixture_error(
        self, fixture: types.ModuleType, tmp_path: Path, raw: object
    ) -> None:
        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(fixture.FixtureError, match=r"(product_private_namespaces|JSON object)"):
            fixture.load_policy(policy)


# ------------------------------------------------------------ the staged run


class RecordedRun:
    """A stub for the fixture's subprocess boundary: records, returns canned stdout."""

    def __init__(self) -> None:
        self.steps: list[tuple[str, tuple[str, ...], Path | None, bool]] = []

    def __call__(self, step: object) -> str:
        # Duck-typed on purpose: the fixture's Step dataclass is the module's
        # own, and the stub must accept whatever the fixture passes.
        self.steps.append((step.description, step.argv, step.cwd, step.expect_failure))  # type: ignore[attr-defined]
        return "11" * 32 + "\n" + "22" * 32 + "\n"  # the key generator's output shape


@pytest.fixture
def record_run(fixture: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> RecordedRun:
    recorded = RecordedRun()
    monkeypatch.setattr(fixture, "_run", recorded.__call__, raising=True)
    return recorded


def _steps(
    recorded: RecordedRun, fragment: str
) -> list[tuple[str, tuple[str, ...], Path | None, bool]]:
    hits = [step for step in recorded.steps if fragment in step[0]]
    assert hits, f"no step matching {fragment!r}; recorded: {[s[0] for s in recorded.steps]}"
    return hits


def _fake_wheel(directory: Path, name: str) -> Path:
    wheel = directory / name
    wheel.write_bytes(b"PK\x03\x04 fake wheel bytes")
    return wheel


def _fake_project(home: Path, family: str) -> tuple[Path, Path]:
    """A scaffolded project (tests + wheel in dist) as the subprocesses would leave it."""
    project = home / "proj"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_sample.py").write_text(
        "def test_ok() -> None:\n    pass\n", encoding="utf-8"
    )
    dist = home / "dist"
    dist.mkdir()
    wheel = _fake_wheel(dist, f"{family}-0.1.0-py3-none-any.whl")
    return project, wheel


PRIVATE_ROOTS_WITH_TOOLS = (
    "maistro",
    "maistro_server",
    "maistro_ext_sdk",
    "maistro_ext_harness",
)


class TestScaffoldRoundTrip:
    def test_the_full_lifecycle_is_executed_in_order(
        self,
        fixture: types.ModuleType,
        tmp_path: Path,
        record_run: RecordedRun,
    ) -> None:
        home = tmp_path / "tool"
        project, wheel = _fake_project(home, "tool")

        fixture.scaffold_round_trip(
            "tool", tmp_path, Path("sdk.whl"), Path("harness.whl"), PRIVATE_ROOTS_WITH_TOOLS
        )

        descriptions = [step[0] for step in record_run.steps]
        # Scaffold → build → venv → install → negative controls → validate →
        # sample tests → conformance → key → certify → verify → mutated refused.
        assert "scaffold the tool project" in descriptions[0]
        assert next(i for i, d in enumerate(descriptions) if "build the tool scaffold" in d) == 1
        assert "create the fresh venv" in descriptions[2]

        # The scaffold runs with the built wheel, not the checkout.
        scaffold_argv = record_run.steps[0][1]
        assert "--with" in scaffold_argv and "sdk.whl" in scaffold_argv
        assert "--family" in scaffold_argv and "tool" in scaffold_argv

        # The tooling venv installs exactly the extension tools; nothing else
        # from the repository (no `-e .`, no repo path on any argv).
        install_argv = _steps(record_run, "install scaffold")[0][1]
        for member in (str(wheel), "sdk.whl", "harness.whl", "pytest", "cryptography"):
            assert member in install_argv, install_argv

        # Every product root except the installed tools is probed unimportable,
        # from the neutral sandbox cwd so a cwd namespace package cannot leak in.
        probes = _steps(record_run, "unimportable")
        probed_roots = {step[1][-1].removeprefix("import ") for step in probes}
        assert probed_roots == {"maistro", "maistro_server", "packages", "extensions"}
        assert all(step[3] is True for step in probes), "negative controls must expect failure"
        assert all(step[2] == home / "sandbox" for step in probes)

        # The generated manifest validates from the installed SDK CLI.
        assert any(
            step[1][:3]
            == (str(home / "venv" / "bin" / "maistro-ext-sdk"), "validate", str(project))
            for step in record_run.steps
        )

        # Sample tests run from a staged copy with the venv interpreter.
        pytest_step = _steps(record_run, "sample tests pass")[0]
        assert pytest_step[1][:3] == (str(home / "venv" / "bin" / "python"), "-m", "pytest")
        assert str(home / "sandbox" / "tests") in pytest_step[1]
        assert "--import-mode=importlib" in pytest_step[1]

        # Conformance, then certify with the generated key, then verify.
        assert _steps(record_run, "conformance suite passes")[0][1][0] == str(
            home / "venv" / "bin" / "maistro-ext-harness"
        )
        certify_step = _steps(record_run, "certify the scaffolded artifact")[0]
        assert "--signing-key-file" in certify_step[1]
        assert (home / "signing-key.hex").read_text(encoding="utf-8") == "11" * 32
        verify_step = _steps(record_run, "verify-certification accepts")[0]
        assert "22" * 32 in verify_step[1]

        # The negative control: one mutated byte must be refused.
        mutated_step = _steps(record_run, "mutated artifact")[0]
        assert mutated_step[3] is True
        mutated = Path(mutated_step[1][mutated_step[1].index("--artifact") + 1])
        original = wheel.read_bytes()
        assert mutated.read_bytes() != original
        assert mutated.read_bytes()[:-1] == original[:-1]  # exactly the last byte

    def test_a_scaffold_dist_with_two_wheels_is_a_fixture_error(
        self,
        fixture: types.ModuleType,
        tmp_path: Path,
        record_run: RecordedRun,
    ) -> None:
        home = tmp_path / "tool"
        _fake_project(home, "tool")
        _fake_wheel(home / "dist", "stray-0.1.0-py3-none-any.whl")
        with pytest.raises(fixture.FixtureError, match="exactly one scaffold wheel"):
            fixture.scaffold_round_trip(
                "tool", tmp_path, Path("sdk.whl"), Path("harness.whl"), PRIVATE_ROOTS_WITH_TOOLS
            )

    def test_the_policy_decides_which_roots_are_probed(
        self,
        fixture: types.ModuleType,
        tmp_path: Path,
        record_run: RecordedRun,
    ) -> None:
        _fake_project(tmp_path / "tool", "tool")
        fixture.scaffold_round_trip(
            "tool", tmp_path, Path("sdk.whl"), Path("harness.whl"), ("maistro",)
        )
        probed_roots = {
            step[1][-1].removeprefix("import ")
            for step in record_run.steps
            if "unimportable" in step[0]
        }
        # The repo-relative sentinels are always probed; the policy's list is
        # what the policy says (the tools are excluded only when it names them).
        assert probed_roots == {"maistro", "packages", "extensions"}


class TestCertifyReferenceExtension:
    def test_the_reference_extension_certifies_through_the_installed_tooling(
        self,
        fixture: types.ModuleType,
        tmp_path: Path,
        record_run: RecordedRun,
    ) -> None:
        home = tmp_path / "reference-greeter"
        dist = home / "dist"
        dist.mkdir(parents=True)
        wheel = _fake_wheel(dist, "reference-greeter-1.0.0-py3-none-any.whl")
        (home / "certification.json").write_text(
            json.dumps({"signature": {"signed": True, "public_key": "cd" * 32}}),
            encoding="utf-8",
        )

        fixture.certify_reference_extension(
            tmp_path, Path("harness.whl"), Path("sdk.whl"), PRIVATE_ROOTS_WITH_TOOLS
        )

        descriptions = [step[0] for step in record_run.steps]
        assert "build the reference extension's wheel" in descriptions[0]
        install_argv = _steps(record_run, "install reference wheel")[0][1]
        for member in (str(wheel), "sdk.whl", "harness.whl", "cryptography"):
            assert member in install_argv, install_argv
        assert "pytest" not in install_argv  # the reference leg does not run sample tests

        probes = _steps(record_run, "unimportable")
        assert {step[1][-1].removeprefix("import ") for step in probes} == {
            "maistro",
            "maistro_server",
            "packages",
            "extensions",
        }
        assert all(step[2] == home for step in probes)  # neutral cwd: not the repo root

        certify_step = _steps(record_run, "certify the reference extension")[0]
        assert fixture.REFERENCE_EXTENSION in [Path(a) for a in certify_step[1]]
        verify_step = _steps(record_run, "verify-certification accepts the reference")[0]
        assert "cd" * 32 in verify_step[1]  # the key from the report, not a generated one

    def test_a_reference_dist_with_two_wheels_is_a_fixture_error(
        self,
        fixture: types.ModuleType,
        tmp_path: Path,
        record_run: RecordedRun,
    ) -> None:
        home = tmp_path / "reference-greeter"
        dist = home / "dist"
        dist.mkdir(parents=True)
        _fake_wheel(dist, "reference-greeter-1.0.0-py3-none-any.whl")
        _fake_wheel(dist, "reference-greeter-2.0.0-py3-none-any.whl")
        with pytest.raises(fixture.FixtureError, match="expected one wheel"):
            fixture.certify_reference_extension(
                tmp_path, Path("harness.whl"), Path("sdk.whl"), PRIVATE_ROOTS_WITH_TOOLS
            )


# ---------------------------------------------------------------------- main


@pytest.fixture
def staged_main(
    fixture: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[types.SimpleNamespace]:
    """`main` with the wheels pre-built and the round trips replaced by spies."""
    calls: dict[str, object] = {"families": [], "reference": 0}
    sdk_wheel = _fake_wheel(tmp_path, "sdk-1.0.0-py3-none-any.whl")
    harness_wheel = _fake_wheel(tmp_path, "harness-1.0.0-py3-none-any.whl")

    def fake_build(dist: Path) -> tuple[Path, Path]:
        return sdk_wheel, harness_wheel

    def fake_round_trip(family: str, *args: object) -> None:
        calls["families"] = [*calls["families"], family]  # type: ignore[union-attr]

    def fake_reference(*args: object) -> None:
        calls["reference"] += 1  # type: ignore[operator]

    monkeypatch.setattr(fixture, "build_first_party_wheels", fake_build)
    monkeypatch.setattr(fixture, "scaffold_round_trip", fake_round_trip)
    monkeypatch.setattr(fixture, "certify_reference_extension", fake_reference)
    yield types.SimpleNamespace(fixture=fixture, calls=calls)


class TestMain:
    def _run_main(
        self,
        fixture: types.ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        *argv: str,
    ) -> int:
        monkeypatch.setattr(sys, "argv", ["check-extension-scaffold.py", *argv])
        return fixture.main()

    def test_every_family_runs_by_default_plus_the_reference(
        self,
        staged_main: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fixture: types.ModuleType = staged_main.fixture
        assert self._run_main(fixture, monkeypatch) == 0
        assert staged_main.calls["families"] == list(fixture.FAMILIES)
        assert staged_main.calls["reference"] == 1
        out = capsys.readouterr().out
        assert f"{len(fixture.FAMILIES)} family template(s)" in out
        assert "reference extension" in out

    def test_family_selects_one_round_trip(
        self,
        staged_main: types.SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fixture: types.ModuleType = staged_main.fixture
        assert self._run_main(fixture, monkeypatch, "--family", "skill") == 0
        assert staged_main.calls["families"] == ["skill"]
        assert staged_main.calls["reference"] == 1
        assert "1 family template(s)" in capsys.readouterr().out

    def test_an_unknown_family_is_an_argument_error(
        self, staged_main: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            self._run_main(staged_main.fixture, monkeypatch, "--family", "not-a-family")
        assert excinfo.value.code == 2

    def test_a_family_failure_skips_the_reference_and_exits_1(
        self,
        staged_main: types.SimpleNamespace,
        fixture: types.ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def failing(family: str, *args: object) -> None:
            if family == "skill":
                raise fixture.FixtureError("the build exploded")

        monkeypatch.setattr(fixture, "scaffold_round_trip", failing)
        assert self._run_main(fixture, monkeypatch, "--family", "tool", "--family", "skill") == 1
        assert staged_main.calls["reference"] == 0, "a failed family must not certify the reference"
        out = capsys.readouterr().out
        assert "FAILED" in out and "[skill] the build exploded" in out

    def test_a_reference_failure_exits_1_and_names_the_subject(
        self,
        staged_main: types.SimpleNamespace,
        fixture: types.ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def failing_reference(*args: object) -> None:
            raise fixture.FixtureError("reference wheel vanished")

        monkeypatch.setattr(fixture, "certify_reference_extension", failing_reference)
        assert self._run_main(fixture, monkeypatch, "--family", "tool") == 1
        assert "[reference-greeter] reference wheel vanished" in capsys.readouterr().out

    def test_main_loads_the_real_policy_by_default(
        self,
        fixture: types.ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, tuple[str, ...]] = {}

        def fake_round_trip(
            family: str,
            workdir: Path,
            sdk: Path,
            harness: Path,
            private_roots: tuple[str, ...],
        ) -> None:
            seen["roots"] = private_roots

        monkeypatch.setattr(
            fixture, "build_first_party_wheels", lambda dist: (Path("s.whl"), Path("h.whl"))
        )
        monkeypatch.setattr(fixture, "scaffold_round_trip", fake_round_trip)
        monkeypatch.setattr(fixture, "certify_reference_extension", lambda *a: None)
        assert (
            self._run_main(fixture, monkeypatch, "--family", "tool", "--policy", str(REAL_POLICY))
            == 0
        )
        assert "maistro_server" in seen["roots"]
