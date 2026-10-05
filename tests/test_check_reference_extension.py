"""Tests for the clean-environment isolation fixture (#951, M9-A3).

The fixture (`scripts/check-reference-extension.py`) builds each extension as
a wheel, installs it plus pytest into a fresh venv, proves the product's own
modules are unimportable there, and runs the extension's tests with that
interpreter.

Most of what can be tested in-process is the plan: the exact commands, their
order (build → venv → install → negative controls → tests), and the
documentation contract — the authoring guide quotes the fixture's sequence,
because "documentation contains enough information to build the reference
package from a clean environment" is only true while the commands are true.
The full physical run executes as its own CI step; the suite runs it only
when `MAISTRO_TEST_EXTENSION_ISOLATION=1` so the ordinary suite stays offline
and fast.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tomllib
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCRIPT = ROOT / "scripts" / "check-reference-extension.py"
GATE_SCRIPT = ROOT / "scripts" / "check-extension-imports.py"
POLICY = ROOT / "extensions" / "namespace-policy.json"
REFERENCE_EXTENSION = ROOT / "extensions" / "reference-greeter"
AUTHORING_GUIDE = ROOT / "docs" / "extensions" / "authoring-guide.md"
REFERENCE_README = REFERENCE_EXTENSION / "README.md"


@pytest.fixture(scope="module")
def fixture() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_reference_extension", FIXTURE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_reference_extension"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_extension_imports_probe", GATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_extension_imports_probe"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# discovery and policy sharing
# ---------------------------------------------------------------------------


def test_fixture_and_gate_share_one_policy_file(
    fixture: types.ModuleType, gate: types.ModuleType
) -> None:
    """One boundary, two enforcers: both scripts must read the same file."""
    assert fixture.DEFAULT_POLICY == gate.DEFAULT_POLICY
    assert fixture.DEFAULT_POLICY.is_file()
    policy = fixture.load_policy(POLICY)
    assert policy["extension_trees"] == ["extensions/*"]


def test_discover_finds_the_reference_extension(fixture: types.ModuleType) -> None:
    projects = fixture.discover_extension_projects(ROOT, fixture.load_policy(POLICY))
    assert [p.name for p in projects] == ["reference-greeter"]
    assert all((p / "pyproject.toml").is_file() for p in projects)


def test_tree_matching_nothing_is_a_fixture_error(
    fixture: types.ModuleType, tmp_path: Path
) -> None:
    policy = {"extension_trees": ["extensions/does-not-exist/*"]}
    with pytest.raises(fixture.FixtureError, match="matched no directory"):
        fixture.discover_extension_projects(ROOT, policy)


def test_unbuildable_extension_is_a_fixture_error(
    fixture: types.ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "hollow").mkdir()
    policy = {"extension_trees": ["*"]}
    with pytest.raises(fixture.FixtureError, match=r"no pyproject\.toml"):
        fixture.discover_extension_projects(tmp_path, policy)


# ---------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------


def test_plan_builds_venv_installs_probes_then_tests(
    fixture: types.ModuleType, tmp_path: Path
) -> None:
    policy = fixture.load_policy(POLICY)
    plan = fixture.isolation_plan(REFERENCE_EXTENSION, policy, tmp_path)

    assert plan[0].argv[:2] == ("uv", "build")
    assert plan[1].argv[:2] == ("uv", "venv")
    install = plan[2]
    assert install.argv[:3] == ("uv", "pip", "install")
    assert any(arg.endswith("*.whl") for arg in install.argv)
    assert "pytest" in install.argv

    # The negative controls are the product-private roots plus the
    # repo-relative sentinels, each expected to FAIL (the import must not
    # resolve in the fresh venv).
    probes = plan[3:-1]
    private_roots = list(policy["product_private_namespaces"])
    assert [step.argv[-1].removeprefix("import ") for step in probes] == [
        *private_roots,
        "packages",
        "extensions",
    ]
    assert all(step.expect_failure for step in probes)

    run = plan[-1]
    assert run.argv[1:4] == ("-m", "pytest", str(REFERENCE_EXTENSION / "tests"))
    # conftest discovery cut off at the extension root: the repository's own
    # conftest.py cannot participate in the isolated run.
    assert "--confcutdir" in run.argv
    assert run.argv[run.argv.index("--confcutdir") + 1] == str(REFERENCE_EXTENSION)


def test_clean_env_strips_inherited_interpreter_state(
    fixture: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/somewhere/evil")
    monkeypatch.setenv("PYTHONHOME", "/also/evil")
    cleaned = fixture.clean_env()
    assert "PYTHONPATH" not in cleaned
    assert "PYTHONHOME" not in cleaned


def test_expect_failure_semantics(fixture: types.ModuleType, tmp_path: Path) -> None:
    """A negative control flips the verdict: success is the violation."""
    always_zero = fixture.Step("t", (sys.executable, "-c", "pass"), expect_failure=True)
    with pytest.raises(fixture.FixtureError, match="succeeded where it must not"):
        fixture._run(always_zero, cwd=tmp_path)

    always_one = fixture.Step("t", (sys.executable, "-c", "raise SystemExit(1)"))
    with pytest.raises(fixture.FixtureError, match="failed"):
        fixture._run(always_one, cwd=tmp_path)


# ---------------------------------------------------------------------------
# the documentation contract (acceptance criterion 2)
# ---------------------------------------------------------------------------


def reference_wheel_filename() -> str:
    """The wheel name `uv build` produces for the reference extension."""
    data = tomllib.loads((REFERENCE_EXTENSION / "pyproject.toml").read_text(encoding="utf-8"))
    name = str(data["project"]["name"]).replace("-", "_")
    version = str(data["project"]["version"])
    return f"{name}-{version}-py3-none-any.whl"


@pytest.mark.parametrize(
    "document",
    [AUTHORING_GUIDE, REFERENCE_README],
    ids=["authoring-guide", "reference-readme"],
)
def test_docs_build_the_reference_package_from_a_clean_environment(document: Path) -> None:
    body = document.read_text(encoding="utf-8")
    # The exact commands the fixture executes, in order.
    assert "uv build --wheel --out-dir dist" in body
    assert "uv venv" in body
    assert "uv pip install --python" in body
    assert "-m pytest tests" in body
    # ...and the artifact those commands produce, so a rename of the package
    # or a version bump cannot leave the docs quietly stale.
    assert reference_wheel_filename() in body


def test_authoring_guide_names_the_boundary_the_gate_enforces() -> None:
    body = AUTHORING_GUIDE.read_text(encoding="utf-8")
    for private_root in ("maistro", "maistro_server"):
        assert private_root in body
    assert "maistro_ext_sdk" in body
    assert "sys.path" in body


# ---------------------------------------------------------------------------
# execution paths (subprocesses mocked; the real run is the CI step)
# ---------------------------------------------------------------------------


def test_load_policy_configuration_errors(fixture: types.ModuleType, tmp_path: Path) -> None:
    with pytest.raises(fixture.FixtureError, match="policy file not found"):
        fixture.load_policy(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(fixture.FixtureError, match="not valid JSON"):
        fixture.load_policy(broken)
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(fixture.FixtureError, match="no extension_trees"):
        fixture.load_policy(empty)


def test_run_returns_stdout_and_reports_failures(fixture: types.ModuleType, tmp_path: Path) -> None:
    ok = fixture.Step("echo", (sys.executable, "-c", "print('ran')"))
    assert "ran" in fixture._run(ok, cwd=tmp_path)
    with pytest.raises(fixture.FixtureError, match="failed \(exit"):
        fixture._run(
            fixture.Step("boom", (sys.executable, "-c", "raise SystemExit(3)")), cwd=tmp_path
        )


def test_isolate_runs_build_venv_install_probes_tests_in_order(
    fixture: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The physical sequence, rehearsed: real files, recorded commands."""
    policy = fixture.load_policy(POLICY)
    workdir = tmp_path / "work"
    dist = workdir / "dist"
    dist.mkdir(parents=True)
    wheel = dist / "reference_greeter-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"payload")  # contents never read; only the path is

    executed: list[tuple[str, str]] = []

    def fake_run(step: fixture.Step, cwd: Path | None) -> str:
        executed.append((step.description, str(cwd)))
        assert not step.expect_failure or step.description.startswith("product-private")
        return ""

    monkeypatch.setattr(fixture, "_run", fake_run)
    fixture.isolate(REFERENCE_EXTENSION, policy, workdir)

    descriptions = [description for description, _ in executed]
    assert descriptions[0] == "build wheel"
    assert descriptions[1] == "create fresh venv"
    # The install step must pin the wheel this run built, not a glob.
    assert descriptions[2].startswith("install wheel")
    assert descriptions[3].startswith("product-private root 'maistro' is unimportable")
    assert descriptions[-1].startswith("run the extension's tests")
    # The build runs in the extension; everything else runs in the sandbox.
    assert executed[0][1] == str(REFERENCE_EXTENSION)
    assert all(cwd.endswith("sandbox") for _, cwd in executed[1:])


def test_isolate_rejects_an_ambiguous_wheel_set(
    fixture: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = fixture.load_policy(POLICY)
    workdir = tmp_path / "work"
    dist = workdir / "dist"
    dist.mkdir(parents=True)
    (dist / "a-1.0.0-py3-none-any.whl").write_bytes(b"")
    (dist / "b-1.0.0-py3-none-any.whl").write_bytes(b"")
    monkeypatch.setattr(fixture, "_run", lambda step, cwd: "")
    with pytest.raises(fixture.FixtureError, match="expected exactly one wheel"):
        fixture.isolate(REFERENCE_EXTENSION, policy, workdir)


def test_main_reports_per_extension_and_fails(
    fixture: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real = REFERENCE_EXTENSION
    monkeypatch.setattr(fixture, "discover_extension_projects", lambda root, policy: [real])

    monkeypatch.setattr(fixture, "isolate", lambda ext, policy, workdir: None)
    assert fixture.main([f"--policy={POLICY}"]) == 0
    assert "ok: reference-greeter builds and tests" in capsys.readouterr().out

    def explode(ext: Path, policy: object, workdir: Path) -> None:
        raise fixture.FixtureError("build wheel failed (exit 1): uv says no")

    monkeypatch.setattr(fixture, "isolate", explode)
    assert fixture.main([f"--policy={POLICY}"]) == 1
    assert "FAIL: reference-greeter" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# the full physical run (opt-in; CI runs it as its own step)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("MAISTRO_TEST_EXTENSION_ISOLATION") != "1",
    reason="runs uv build + a fresh venv + a wheel install; executed unconditionally "
    "by the dedicated CI step (scripts/check-reference-extension.py)",
)
def test_full_isolation_run_end_to_end(fixture: types.ModuleType) -> None:
    assert fixture.main([f"--policy={POLICY}"]) == 0
