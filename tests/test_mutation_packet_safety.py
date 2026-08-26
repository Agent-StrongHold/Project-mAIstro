"""A mutation run cannot leave a live mutant on disk (#419).

Cosmic-ray mutates the source in place and restores it between mutants. Kill
the process mid-mutant — a timeout, a cancelled job, Ctrl-C — and the mutation
stays on disk.

On a CI runner that is harmless: the checkout is thrown away. Locally it is
not. Observed twice while measuring #419, in the gate this repository uses to
decide whether imports resolve:

    if pkg.is_dir() and (pkg // "__init__.py").is_file():   # was /
    for alias in []:                                        # was node.names

Only a test run afterwards noticed. A leftover mutant is worse than an ordinary
dirty file because it reads as deliberate — a small, plausible, syntactically
valid change a reviewer would have to know the original to question. One of
those two was still on disk across a `git checkout`, because an overlapping
worker re-mutated the file after the restore.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_packet.py"


@pytest.fixture(scope="module")
def packet():
    # `mutation_packet` imports its sibling `mutation_resume` at module scope,
    # which only resolves with scripts/ on the path — the same shape the
    # packet runner itself executes under.
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("_mutation_packet", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "target.py"
    path.write_text("def f(a, b):\n    return a | b\n", encoding="utf-8")
    return path


class TestTheSourceSurvivesTheRun:
    def test_a_clean_run_leaves_the_file_untouched(self, packet, source):
        before = source.read_bytes()
        with packet._restored(source):
            pass
        assert source.read_bytes() == before

    def test_a_mutation_left_behind_is_restored(self, packet, source, capsys):
        """The exact shape of the incident: the body exits with a mutated file
        still on disk."""
        before = source.read_bytes()
        with packet._restored(source):
            source.write_text("def f(a, b):\n    return a & b\n", encoding="utf-8")
        assert source.read_bytes() == before
        assert "restored" in capsys.readouterr().err

    def test_it_restores_when_the_run_raises(self, packet, source):
        """A cancelled job raises rather than returning. Restoring only on the
        happy path would miss every case this exists for."""
        before = source.read_bytes()
        with pytest.raises(RuntimeError), packet._restored(source):
            source.write_text("mutated\n", encoding="utf-8")
            raise RuntimeError("worker died")
        assert source.read_bytes() == before

    def test_it_says_so_rather_than_restoring_silently(self, packet, source, capsys):
        """A silent restore hides that an interrupted run happened at all, and
        the run's results are then partial without anyone knowing."""
        with packet._restored(source):
            source.write_text("mutated\n", encoding="utf-8")
        assert str(source) in capsys.readouterr().err

    def test_a_clean_run_says_nothing(self, packet, source, capsys):
        with packet._restored(source):
            pass
        assert capsys.readouterr().err == ""

    def test_it_restores_bytes_not_git_state(self, packet, tmp_path):
        """From the bytes read before the run, not from git — so it works on an
        already-dirty tree and cannot discard unrelated edits. Restoring from
        git would silently revert whatever the developer was working on."""
        path = tmp_path / "dirty.py"
        path.write_text("uncommitted work\n", encoding="utf-8")
        with packet._restored(path):
            path.write_text("mutated\n", encoding="utf-8")
        assert path.read_text(encoding="utf-8") == "uncommitted work\n"


def _report() -> dict[str, object]:
    return {
        "raw": {"total": 3},
        "adjusted": {"total": 2, "killed": 2, "rate": 1.0},
        "viable": [],
        "non_viable": [],
        "invalid": [],
        "undetermined": [],
        "pending": 0,
    }


ENVIRONMENT = {
    "runner": "ubuntu-24.04",
    "python_version": "3.12.7",
    "cosmic_ray_version": "8.4.6",
    "pytest_version": "8.3.4",
    "tool_fingerprint": "deadbeef",
}


class _Recorder:
    """Stands in for `run`, so the packet's ordering can be asserted without
    invoking cosmic-ray. Supplies the two side effects `execute_source` reads
    back from the real subprocesses: the viability report, and -- when asked --
    a mutant left on disk by `cosmic-ray exec`.
    """

    def __init__(self, source: Path, *, leave_mutant: bool = False) -> None:
        self.source = source
        self.leave_mutant = leave_mutant
        self.commands: list[list[str]] = []
        self.source_during_exec = b""

    def __call__(self, command: list[str], *, env=None, stdout=None) -> None:
        self.commands.append(command)
        if command[:2] == ["cosmic-ray", "exec"]:
            self.source_during_exec = self.source.read_bytes()
            if self.leave_mutant:
                self.source.write_text("def f(a, b):\n    return a & b\n", encoding="utf-8")
        if any(part.endswith("mutation_viability.py") for part in command):
            Path(command[-1]).write_text(json.dumps(_report()), encoding="utf-8")

    def index_of(self, *prefix: str) -> int:
        for position, command in enumerate(self.commands):
            if command[: len(prefix)] == list(prefix):
                return position
        raise AssertionError(f"{prefix} never ran; ran {self.commands}")

    def index_of_script(self, name: str) -> int:
        for position, command in enumerate(self.commands):
            if any(part.endswith(name) for part in command):
                return position
        raise AssertionError(f"{name} never ran; ran {self.commands}")


class Packet(NamedTuple):
    execute: Callable[..., tuple[_Recorder, dict[str, object]]]
    source: Path


@pytest.fixture
def packet_run(packet, tmp_path, monkeypatch) -> Packet:
    """`execute_source` writes its config, session and checkpoints relative to
    the working directory, so give it a throwaway one.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "packages").mkdir()
    source = tmp_path / "target.py"
    source.write_text("def f(a, b):\n    return a | b\n", encoding="utf-8")
    (tmp_path / "test_target.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")

    def execute(*, leave_mutant: bool = False) -> tuple[_Recorder, dict[str, object]]:
        recorder = _Recorder(source, leave_mutant=leave_mutant)
        monkeypatch.setattr(packet, "run", recorder)
        checkpoint = packet.execute_source(
            "target.py",
            "test_target.py",
            ENVIRONMENT,
            commit="c0ffee",
            run_id="1",
            run_attempt="1",
            uploader=tmp_path / "upload.js",
        )
        return recorder, checkpoint

    return Packet(execute, source)


class TestTheGuardsAreWiredIntoTheRun:
    """The restore and the annotation filter are worth nothing unless the
    packet runner actually calls them, in the right order. Asserting they exist
    as module members would pass with the calls deleted.
    """

    def test_the_filter_runs_after_init_and_before_exec(self, packet_run):
        """Between the two: before `init` there is no session of mutants to
        skip, and after `exec` the run has already paid for every one of them
        (#419)."""
        recorder, _ = packet_run.execute()
        assert (
            recorder.index_of("cosmic-ray", "init")
            < recorder.index_of_script("mutation_filter_annotations.py")
            < recorder.index_of("cosmic-ray", "exec")
        )

    def test_the_filter_is_pointed_at_this_run_s_session(self, packet_run):
        recorder, _ = packet_run.execute()
        command = recorder.commands[recorder.index_of_script("mutation_filter_annotations.py")]
        session = recorder.commands[recorder.index_of("cosmic-ray", "init")][3]
        assert session in command
        assert "--report" in command, "a silent filter cannot be audited afterwards"

    def test_a_mutant_left_by_exec_is_restored(self, packet_run):
        """The incident end to end: the guard has to wrap the real `exec` call,
        not merely exist in the module."""
        before = packet_run.source.read_bytes()
        packet_run.execute(leave_mutant=True)
        assert packet_run.source.read_bytes() == before

    def test_exec_runs_against_the_unmutated_source(self, packet_run):
        """Restoring afterwards is no help if the guard snapshots the wrong
        moment -- cosmic-ray has to start from the file as committed."""
        recorder, _ = packet_run.execute()
        assert recorder.source_during_exec == packet_run.source.read_bytes()

    def test_it_checkpoints_what_the_run_reported(self, packet_run):
        _, checkpoint = packet_run.execute()
        assert checkpoint["mutant_count"] == 3
        assert checkpoint["viable_mutants"] == 2
        assert checkpoint["verified_commit"] == "c0ffee"
        assert checkpoint["complete"] is True
