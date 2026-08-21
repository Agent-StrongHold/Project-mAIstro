"""LiveCodeFixer.fix_and_score never raises — a transient gateway/agent failure
becomes a stub result (no real signal), mirroring _run_variant's contract, so one
flaky LLM call can't kill a multi-hour evolution run (a live httpx.ReadTimeout did)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro_rsi.code_fixer import LiveCodeFixer


def _make_baseline(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-c", "core.longpaths=true", *a], cwd=str(path), capture_output=True, check=True
    )
    run("init", "-q")
    run("config", "user.email", "rsi@test.local")
    run("config", "user.name", "RSI Test")
    (path / "x.txt").write_text("0\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "init")
    run("checkout", "-q", "-B", "rsi-baseline")
    return path


@pytest.mark.asyncio
async def test_agent_failure_becomes_a_stub_result_not_a_crash(tmp_path, monkeypatch) -> None:
    baseline = _make_baseline(tmp_path / "baseline")
    fixer = LiveCodeFixer(baseline, test_command="exit 0")

    def boom(*_a, **_kw):
        raise RuntimeError("gateway 400 / ReadTimeout / anything transient")

    import maistro_rsi.code_fixer as cf

    monkeypatch.setattr(cf, "make_builders_apply_patch", boom)

    from maistro_rsi.competitors import Competitor

    accepted, composite, is_stub = await fixer.fix_and_score(Competitor(model="code"), "x.txt")
    assert (accepted, composite, is_stub) == (False, 0.0, True)  # stub: no real signal
    # The throwaway worktree was cleaned up despite the failure.
    assert not list(baseline.parent.glob("evo-*"))
