"""Autonomous RSI refuses Tier-3 container isolation (ADR-093 decision 6).

`python -m maistro_rsi run/evolve --isolation container` is the unattended
multi-cycle surface of this package, and ``local_loop.make_builders_apply_patch``
would back it with `ContainerBuilderSandbox` — a Tier-3 hardened container. The
2026-08-31 D-04 regression behind issue #80's reopening found exactly this gap:
the flag offered Tier-3 isolation to autonomous code with no execution-mode or
tier guard anywhere on the path.

These tests pin the refusal at both entries the finding named:

- the CLI dispatcher (`__main__._run`/`_evolve`) — the operator surface;
- the library boundary (`LocalRsiLoop.run`) — because `LocalRsiConfig` is a
  public constructor a programmatic caller can reach without the CLI.

The rule itself is data-driven from `maistro.sandbox.policy` (`MODE_FLOORS`,
`tier_satisfies`), so the last test also pins the linkage: if the canonical
autonomous floor ever drops to Tier 3 the refusal disappears *because the
policy changed*, and this suite says which test to re-read — not a hardcoded
string drifting away from the ADR it cites.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro.sandbox.policy import MODE_FLOORS, ExecutionMode, tier_satisfies
from maistro_rsi import __main__ as entry
from maistro_rsi.contained_validation import ContainmentUnavailable
from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop, autonomous_isolation_refusal

RUN_ARGS = ["run", "--repo", "/nonexistent", "--test-cmd", "true"]
EVOLVE_ARGS = [
    "evolve",
    "--repo",
    "/nonexistent",
    "--test-cmd",
    "true",
    "--target",
    "x.py",
]


def _git(cwd: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} rc={proc.returncode}: {proc.stderr.strip()}")


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "rsi@test.local")
    _git(path, "config", "user.name", "RSI Test")
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


class TestCliRefusal:
    def test_run_refuses_container_isolation_before_any_work(self, capsys: pytest.CaptureFixture):
        """The refusal fires ahead of the repo check: no clone, no gateway
        probe, nothing — the run must not start, not start-then-fail."""
        code = entry.main([*RUN_ARGS, "--isolation", "container"])

        assert code == 2
        err = capsys.readouterr().err
        assert "refusing to start" in err
        assert "ADR-093" in err
        # Names the floor it enforced, so the operator can tell tier from tier.
        assert MODE_FLOORS[ExecutionMode.AUTONOMOUS] in err

    def test_evolve_refuses_container_isolation(self, capsys: pytest.CaptureFixture):
        code = entry.main([*EVOLVE_ARGS, "--isolation", "container"])

        assert code == 2
        assert "refusing to start" in capsys.readouterr().err

    def test_run_local_isolation_is_not_refused_by_the_tier_guard(
        self, capsys: pytest.CaptureFixture
    ):
        """`local` is an operator's explicit host choice, not a sandbox tier;
        the tier guard stays silent and the run proceeds to its own next gate
        (here: the missing repository)."""
        code = entry.main(RUN_ARGS)

        assert code == 2
        assert "is not a git repository" in capsys.readouterr().err


class TestLibraryRefusal:
    def test_loop_run_refuses_container_config(self, tmp_path: Path) -> None:
        """A programmatic caller bypassing the CLI hits the same floor at
        `LocalRsiLoop.run()` — the autonomous entry, before any baseline
        clone happens."""
        repo = _make_repo(tmp_path / "src")
        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="true",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
            isolation="container",
        )

        with pytest.raises(ContainmentUnavailable, match="ADR-093"):
            LocalRsiLoop(config).run()

    def test_loop_local_config_is_not_tier_refused(self, tmp_path: Path) -> None:
        """The local loop keeps running: the guard refuses autonomy-behind-
        Tier-3, not the local isolation an operator chose for their machine."""
        repo = _make_repo(tmp_path / "src")

        def bump(ws: Path) -> None:
            f = ws / "value.txt"
            f.write_text(f.read_text() + "x\n", encoding="utf-8")

        async def apply(sandbox, workspace: str, model: str | None = None) -> None:
            bump(Path(workspace))

        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="true",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
            isolation="local",
        )
        result = LocalRsiLoop(config, apply_patch=apply).run()

        assert result.cycles and result.cycles[0].tests_passed


class TestPolicyLinkage:
    def test_the_refusal_is_the_policy_not_a_string(self) -> None:
        """The guard compares the backend's tier against the canonical
        autonomous floor. Pin both halves of that comparison so a later floor
        change (Tier-2 backend lands, floor revisited) shows up here as a
        deliberate policy edit instead of a silently stale refusal."""
        assert autonomous_isolation_refusal("container") is not None
        assert not tier_satisfies("container", MODE_FLOORS[ExecutionMode.AUTONOMOUS])
        # And the None cases: unstated/local vocabulary is not this guard's
        # question — it neither clears nor damns a backend it cannot name.
        assert autonomous_isolation_refusal("local") is None
        assert autonomous_isolation_refusal("vm") is None
