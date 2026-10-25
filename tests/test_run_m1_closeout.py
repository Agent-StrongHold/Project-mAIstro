"""The named strict M1-closeout invocation is the contract CI shells out to.

``scripts/run-m1-closeout.py`` (#1069) is the closure-candidate entry point:
it must select the fail-closed mode through both strict spellings so early-return
blockers and abstaining scenarios cannot pass, it must run the real parity suite
rather than a reduced subset, and it must propagate the suite's exit code so a
strict failure reds the release job. These tests execute the script in process
with the subprocess boundary stubbed, so the release workflow's command is
checked without recursively running the suite — and so the diff-coverage gate
measures the script the release workflow actually executes.
"""

from __future__ import annotations

import importlib.util
import runpy
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run-m1-closeout.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_m1_closeout", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class SuiteCall:
    """One stubbed child-pytest invocation."""

    command: list[str]
    env: dict[str, str]
    check: bool
    returncode: int = 0


@dataclass
class SuiteStub:
    """Replaces the child pytest process, recording every invocation."""

    exit_code: int = 0
    calls: list[SuiteCall] = field(default_factory=list)

    def __call__(self, command: list[str], env: dict[str, str], check: bool):
        call = SuiteCall(
            command=list(command), env=dict(env), check=check, returncode=self.exit_code
        )
        self.calls.append(call)
        return subprocess.CompletedProcess(command, self.exit_code)


@pytest.fixture
def stub_suite(monkeypatch: pytest.MonkeyPatch) -> SuiteStub:
    """Patch `subprocess.run` globally: the script imports the same module
    object a `runpy` execution of the file sees."""
    stub = SuiteStub()
    monkeypatch.setattr(subprocess, "run", stub)
    return stub


def test_main_sets_both_strict_spellings_and_runs_the_parity_suite(
    stub_suite: SuiteStub,
) -> None:
    module = _load_script()

    assert module.main() == 0

    (call,) = stub_suite.calls
    assert "tests/cross_product_parity" in call.command
    assert call.env["MAISTRO_PARITY_MODE"] == "m1-closeout"
    assert call.env["MAISTRO_PARITY_STRICT"] == "1"


def test_main_propagates_a_failing_suite_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strict failure must fail the job: no swallowing, no check=True raise."""
    stub = SuiteStub(exit_code=1)
    monkeypatch.setattr(subprocess, "run", stub)
    module = _load_script()

    assert module.main() == 1
    assert stub.calls[0].check is False


def test_the_script_runs_as_a_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `__main__` guard: CI shells out, so a file that imports but does not
    run would pass the tests above and still fail the pipeline."""
    stub = SuiteStub()
    monkeypatch.setattr(subprocess, "run", stub)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert excinfo.value.code == 0
    (call,) = stub.calls
    assert call.env["MAISTRO_PARITY_STRICT"] == "1"
