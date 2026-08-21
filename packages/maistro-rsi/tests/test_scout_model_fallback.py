"""Integration: LocalRsiLoop actually fails over to the next-ranked scout
model when the first is benched, and credits whichever model served scout
when its cycle gets promoted. This is the fix for the real failure observed
in the 150-cycle run: the scout's single static model got chronically
benched around cycle 20 and silently produced nothing for the rest of the
run (scout_shortlist swallows LLM errors and returns [])."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import maistro_rsi.scout as scout_module
from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop
from maistro_rsi.scout import ScoutItem


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "rsi@test.local")
    _git(path, "config", "user.name", "RSI Test")
    (path / "target.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _loop(tmp_path: Path, **overrides) -> LocalRsiLoop:
    repo = _make_repo(tmp_path / "src")
    defaults = {
        "repo_path": str(repo),
        "test_command": "exit 0",
        "work_root": str(tmp_path / "work"),
        "max_cycles": 1,
        "scout": True,
        "targets": ["target.py"],
        "report_dir": str(tmp_path / "reports"),
        "genome_models": ["model-a", "model-b", "model-c"],
    }
    defaults.update(overrides)
    config = LocalRsiConfig(**defaults)
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    return loop


_ITEM = ScoutItem(kind=ImprovementKind.NEW_TEST, location="target.py", instruction="add a test")


def test_cycle_slots_skips_benched_model_and_tries_next(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path)
    loop._bench["model-a"] = time.monotonic() + 1000  # model-a benched

    calls = []

    def fake_shortlist(source, tests, uncovered, llm_call, **kw):
        calls.append(llm_call.model)
        if llm_call.model == "model-a":
            raise AssertionError("must not call the benched model")
        return [_ITEM]

    monkeypatch.setattr(scout_module, "scout_shortlist", fake_shortlist)
    slots = loop._cycle_slots(1)

    assert calls == ["model-b"], "model-a was benched and must be skipped entirely"
    assert loop._last_scout_model == "model-b"
    assert len(slots) == 1


def test_cycle_slots_falls_over_through_multiple_benched_models(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path)
    loop._bench["model-a"] = time.monotonic() + 1000
    loop._bench["model-b"] = time.monotonic() + 1000

    def fake_shortlist(source, tests, uncovered, llm_call, **kw):
        return [_ITEM] if llm_call.model == "model-c" else []

    monkeypatch.setattr(scout_module, "scout_shortlist", fake_shortlist)
    slots = loop._cycle_slots(1)

    assert loop._last_scout_model == "model-c"
    assert len(slots) == 1


def test_cycle_slots_falls_back_to_generic_when_every_model_fails(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path)

    monkeypatch.setattr(scout_module, "scout_shortlist", lambda *a, **k: [])
    slots = loop._cycle_slots(1)

    assert loop._last_scout_model is None
    assert len(slots) == 1
    assert slots[0][2] == ImprovementKind.DOC  # the generic fallback slot


def test_explicit_scout_model_is_tried_first_but_still_falls_over(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, scout_model="model-pinned")
    loop._bench["model-pinned"] = time.monotonic() + 1000

    calls = []

    def fake_shortlist(source, tests, uncovered, llm_call, **kw):
        calls.append(llm_call.model)
        return [_ITEM] if llm_call.model == "model-a" else []

    monkeypatch.setattr(scout_module, "scout_shortlist", fake_shortlist)
    loop._cycle_slots(1)

    assert "model-pinned" not in calls, "a benched pin must still be skipped, not force-called"
    assert loop._last_scout_model == "model-a"


def test_scout_fallback_catalog_defaults_to_genome_models(tmp_path) -> None:
    loop = _loop(tmp_path)
    assert loop._scout_fallback_catalog() == ["model-a", "model-b", "model-c"]


def test_scout_fallback_catalog_falls_back_to_model_when_no_genome_models(tmp_path) -> None:
    loop = _loop(tmp_path, genome_models=[], model="solo-model")
    assert loop._scout_fallback_catalog() == ["solo-model"]


def test_promotion_credits_the_scout_model_and_persists(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path)

    def fake_shortlist(source, tests, uncovered, llm_call, **kw):
        return [_ITEM] if llm_call.model == "model-b" else []

    monkeypatch.setattr(scout_module, "scout_shortlist", fake_shortlist)

    async def apply(sandbox, workspace, model=None):
        (Path(workspace) / "new_file.py").write_text("x = 1\n", encoding="utf-8")

    loop._injected_apply = apply
    loop._config.use_fitness = False
    loop._config.competitors = []  # use the default single-competitor path

    outcome = loop._run_cycle(1)
    assert outcome.promoted is True

    state_path = Path(loop._config.report_dir) / "scout_fallback.json"
    assert state_path.is_file()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["scores"] == {"model-b": 1}


def test_no_report_dir_scout_fallback_stays_in_memory_only(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, report_dir=None)

    monkeypatch.setattr(scout_module, "scout_shortlist", lambda *a, **k: [_ITEM])
    loop._cycle_slots(1)
    loop._record_scout_success(loop._last_scout_model)  # must not raise without report_dir

    assert loop._scout_fallback.scores  # still tracked in memory
