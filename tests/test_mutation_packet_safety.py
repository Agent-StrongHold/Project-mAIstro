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
import sys
from pathlib import Path

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
