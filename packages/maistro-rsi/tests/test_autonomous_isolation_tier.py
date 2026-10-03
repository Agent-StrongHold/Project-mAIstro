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

The rule itself is driven by the ADR-093 floors mirrored in
`maistro_rsi.isolation_floor` — a mirror, not an import, because importing
`maistro.sandbox.policy` from the loop executes `maistro/sandbox/__init__.py`
and drags ~220 unprotected maistro-core modules into the promotion closure
that `scripts/check-promotion-surface.py` guards. So this suite pins both
halves: the refusal's behavior, and the mirror's parity with the canonical
`maistro.sandbox.policy` (`MODE_FLOORS`, `tier_satisfies`) — if the canonical
autonomous floor or ladder ever changes, these tests fail until the mirror
follows deliberately.

The 2026 round-22 repair (#80) closed the mirror image of the original gap:
`--isolation` *defaulted* to `local`, so the unattended loop ran candidate
work through `LocalWorktreeSandbox` on the host by omission — the
bare-subprocess tier ADR-093 decision 5 forbids, reached by nobody's
decision. An unstated isolation now refuses at every entry (CLI, config,
factory); a stated `local` proceeds as ADR-082926-a6ab's operator choice.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import get_args

import pytest

from maistro.sandbox.policy import (
    MODE_FLOORS,
    ExecutionMode,
    tier_satisfies,
)
from maistro.sandbox.policy import (
    IsolationTier as CanonicalIsolationTier,
)
from maistro_rsi import __main__ as entry
from maistro_rsi import isolation_floor as mirror
from maistro_rsi.contained_validation import ContainmentUnavailable
from maistro_rsi.local_loop import (
    LocalRsiConfig,
    LocalRsiLoop,
    autonomous_isolation_refusal,
    make_builders_apply_patch,
)

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

    def test_run_without_isolation_refuses_fail_closed(self, capsys: pytest.CaptureFixture):
        """An unstated isolation is nobody's choice: the old `Default: local`
        silently handed unattended candidate work to `LocalWorktreeSandbox` —
        the bare-subprocess tier ADR-093 decision 5 forbids. The refusal fires
        before the repo check: nothing starts."""
        code = entry.main(RUN_ARGS)

        assert code == 2
        err = capsys.readouterr().err
        assert "refusing to start" in err
        assert "no isolation was chosen" in err
        # Names the operator's two ways out instead of choosing for them.
        assert "--isolation local" in err
        assert "ADR-093" in err

    def test_evolve_without_isolation_refuses_fail_closed(self, capsys: pytest.CaptureFixture):
        code = entry.main(EVOLVE_ARGS)

        assert code == 2
        err = capsys.readouterr().err
        assert "refusing to start" in err
        assert "no isolation was chosen" in err

    def test_run_explicit_local_isolation_is_not_refused_by_the_tier_guard(
        self, capsys: pytest.CaptureFixture
    ):
        """`local` stated explicitly is ADR-082926-a6ab's operator choice, not
        a sandbox tier; the tier guard stays silent and the run proceeds to
        its own next gate (here: the missing repository)."""
        code = entry.main([*RUN_ARGS, "--isolation", "local"])

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

    def test_loop_unstated_isolation_refuses(self, tmp_path: Path) -> None:
        """A programmatic caller who never stated an isolation hits the same
        fail-closed refusal at `run()` — the old dataclass default (`local`)
        was the bare-subprocess tier chosen by omission."""
        repo = _make_repo(tmp_path / "src")
        config = LocalRsiConfig(
            repo_path=str(repo),
            test_command="true",
            work_root=str(tmp_path / "work"),
            max_cycles=1,
        )

        with pytest.raises(ContainmentUnavailable, match="no isolation was chosen"):
            LocalRsiLoop(config).run()

    def test_unstated_isolation_refuses_rather_than_degrading_to_the_host(self) -> None:
        """The guard's own refusal for an unstated isolation names the floor
        it enforces and the operator's ways out."""
        refusal = autonomous_isolation_refusal("")

        assert refusal is not None
        assert "no isolation was chosen" in refusal
        assert "ADR-093" in refusal
        assert "--isolation local" in refusal


class TestFactoryRefusal:
    """`make_builders_apply_patch` is the one place a sandbox tier is chosen;
    its old `isolation="local"` default let a direct caller build a
    `LocalWorktreeSandbox` without ever stating a choice."""

    def test_factory_refuses_an_unstated_isolation(self) -> None:
        """The runtime unstated case: a config's "" default flowing straight
        into the factory (the type system already refuses omission)."""
        with pytest.raises(ContainmentUnavailable, match="no isolation was chosen"):
            make_builders_apply_patch("objective", isolation="")

    def test_factory_refuses_a_name_it_cannot_construct(self) -> None:
        """A typo or an unwired backend name must never fall into the apply
        closure's host-worktree branch — that would be the bare-subprocess
        tier reached by accident instead of decision."""
        with pytest.raises(ContainmentUnavailable, match="does not name a sandbox backend"):
            make_builders_apply_patch("objective", isolation="locaal")

    def test_factory_refuses_container(self) -> None:
        with pytest.raises(ContainmentUnavailable, match="ADR-093"):
            make_builders_apply_patch("objective", isolation="container")

    def test_factory_allows_explicit_local(self) -> None:
        apply_fn = make_builders_apply_patch("objective", isolation="local")

        assert callable(apply_fn)


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


class TestMirrorParity:
    def test_mirror_is_the_canonical_policy(self) -> None:
        """`maistro_rsi.isolation_floor` exists only because the promotion
        closure forbids the loop importing `maistro.sandbox.policy` (its
        package initializer drags ~220 unprotected maistro-core modules onto
        the promotion path — the exact regression repair round 5 fixed). A
        mirror that drifts is a guard enforcing a floor ADR-093 no longer
        declares, so every comparison the guard can make must agree with the
        canonical policy, tier for tier, and the mirrored autonomous floor
        must *be* the canonical one.

        A tier the canonical ladder adds but the mirror lacks raises
        ValueError here rather than passing — that is the point.
        """
        canonical_tiers = get_args(CanonicalIsolationTier)

        assert MODE_FLOORS[ExecutionMode.AUTONOMOUS] == mirror.AUTONOMOUS_FLOOR
        assert tuple(mirror.TIER_ORDER) == tuple(canonical_tiers)
        for available in canonical_tiers:
            for required in canonical_tiers:
                assert mirror.tier_satisfies(available, required) == tier_satisfies(
                    available, required
                ), f"mirror disagrees with the canonical ladder at {available!r} vs {required!r}"
