"""Ambient credentials do not reach candidate execution environments (#78).

Every test here pins the same property at a different seam: a process that
executes candidate code (the RSI harness's own test vector, a sandbox shell,
the fitness runner) must start from the credential boundary's minimal
environment, not the harness's inherited one. The live case is
``LITELLM_MASTER_KEY`` — ``maistro_rsi.gateway`` reads it from the RSI
process's environment, so before the boundary any candidate ``bash -c``
inherited a working gateway credential simply by existing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from maistro.sandbox.credential_boundary import candidate_env
from maistro_rsi.sandbox.local import LocalSandbox as SbxLocalSandbox

# LocalSandbox.exec (both of them) shells out to `bash`; the assertions run
# real subprocesses, so they are POSIX-only like the code under test.
posix_exec_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="candidate exec paths are POSIX-only (bash)",
)

#: Variables the shell itself sets at startup (SHLVL, PWD) or exports for the
#: running command (`_`). They are shell-provided, not ambient-inherited — a
#: child that received them from the harness would carry the harness's values,
#: which the secrets assertions below rule out separately.
_SHELL_PROVIDED = frozenset({"SHLVL", "PWD", "_"})


class _Completed:
    returncode = 0
    stdout = ""
    stderr = ""


@posix_exec_only
class TestSbxLocalSandboxExec:
    """`maistro_rsi.sandbox.local.LocalSandbox` — the backend the sbx kit
    selects, where the harness process itself holds the gateway key."""

    @pytest.mark.asyncio
    async def test_exec_does_not_inherit_ambient_secrets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")
        # Split literal (gitleaks doctrine): a secret-shaped value must not
        # appear whole on any single line. The specimen is AWS's documented
        # example key — its realistic shape is the point of the test.
        aws_example_secret = (
            "wJalrXUtnFEMI/"  # fragment only — never the whole key on one line
            "K7MDENG/bPxRfiCY"
        )
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", aws_example_secret)
        async with SbxLocalSandbox(str(tmp_path)) as sandbox:
            rc, output = await sandbox.exec("env")
        assert rc == 0
        assert "sk-live-harness-secret" not in output
        assert "AWS_SECRET_ACCESS_KEY" not in output

    @pytest.mark.asyncio
    async def test_exec_env_is_exactly_the_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No more, no less: the child's environment equals the boundary's —
        pinned as a whole so a future edit cannot quietly add a passthrough."""
        monkeypatch.setenv("HARNESS_ONLY_FLAG", "present")
        async with SbxLocalSandbox(str(tmp_path)) as sandbox:
            rc, output = await sandbox.exec("env")
        assert rc == 0
        seen = {line.split("=", 1)[0] for line in output.splitlines() if "=" in line}
        assert seen == set(candidate_env()) | _SHELL_PROVIDED

    @pytest.mark.asyncio
    async def test_exec_carries_only_explicit_provider_grants(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")
        sandbox = SbxLocalSandbox(str(tmp_path), grants={"MY_TOOL_TOKEN": "scope:limited"})
        try:
            rc, out = await sandbox.exec("printenv MY_TOOL_TOKEN")
            assert (rc, out.strip()) == (0, "scope:limited")
            rc, out = await sandbox.exec("printenv LITELLM_MASTER_KEY")
            assert rc != 0
        finally:
            await sandbox.destroy()

    @pytest.mark.asyncio
    async def test_candidate_export_cannot_widen_later_execs(self, tmp_path: Path) -> None:
        """#78 AC: candidate code cannot widen its own credential scope. The
        env is rebuilt from the boundary on every exec, so a candidate's own
        `export` in one exec never persists into the next."""
        async with SbxLocalSandbox(str(tmp_path)) as sandbox:
            rc, _ = await sandbox.exec("export SMUGGLED_TOKEN=pwned; true")
            assert rc == 0
            rc, _ = await sandbox.exec("printenv SMUGGLED_TOKEN")
            assert rc != 0


@posix_exec_only
class TestLocalLoopSandboxExec:
    """`local_loop.LocalSandbox` — the host-backed worktree sandbox used when
    an operator chooses local isolation; its exec runs operator test/health
    commands whose imports are candidate code."""

    @pytest.mark.asyncio
    async def test_exec_does_not_inherit_ambient_secrets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from maistro_rsi.local_loop import LocalSandbox

        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")
        sandbox = LocalSandbox(tmp_path)
        rc, output = await sandbox.exec("env")
        assert rc == 0
        assert "sk-live-harness-secret" not in output
        seen = {line.split("=", 1)[0] for line in output.splitlines() if "=" in line}
        assert seen == set(candidate_env()) | _SHELL_PROVIDED


class TestLocalLoopHostTestPaths:
    """`LocalRsiLoop._run_tests` host paths — the non-container fallbacks that
    run the candidate's test vector directly on the host."""

    @pytest.fixture
    def recorded(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")

        def _fake_run(command: Any, **kwargs: Any) -> _Completed:
            calls.append({"command": command, **kwargs})
            return _Completed()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        return calls

    @staticmethod
    def _loop(config: Any) -> Any:
        from maistro_rsi.local_loop import LocalRsiLoop

        loop = object.__new__(LocalRsiLoop)
        loop._config = config
        return loop

    @staticmethod
    def _config(tmp_path: Path, **overrides: Any) -> Any:
        from maistro_rsi.local_loop import LocalRsiConfig

        base: dict[str, Any] = {
            "repo_path": str(tmp_path / "repo"),
            "test_command": "python -m pytest -q",
            "work_root": str(tmp_path / "work"),
        }
        base.update(overrides)
        return LocalRsiConfig(**base)

    def test_argv_path_runs_behind_the_boundary(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        self._loop(self._config(tmp_path, test_argv=("python", "-m", "pytest")))._run_tests(
            tmp_path
        )
        env = recorded[0]["env"]
        assert env == candidate_env()
        assert "LITELLM_MASTER_KEY" not in env

    def test_shell_path_runs_behind_the_boundary(
        self, tmp_path: Path, recorded: list[dict[str, Any]]
    ) -> None:
        self._loop(self._config(tmp_path))._run_tests(tmp_path)
        env = recorded[0]["env"]
        assert env == candidate_env()
        assert "LITELLM_MASTER_KEY" not in env


class TestFitnessTestCommand:
    """`candidate_fitness._run` — the fitness runner's test command, which
    imports the candidate's conftest and test modules."""

    def test_run_passes_the_boundary_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import maistro_rsi.candidate_fitness as cf

        seen: dict[str, Any] = {}
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-harness-secret")

        def _fake_run(command: Any, **kwargs: Any) -> _Completed:
            seen.update(kwargs)
            return _Completed()

        monkeypatch.setattr(cf.subprocess, "run", _fake_run)
        cf._run("python -m pytest -q", tmp_path := Path("."), timeout=5)  # noqa: F841
        assert seen["env"] == candidate_env()
        assert "LITELLM_MASTER_KEY" not in seen["env"]

    def test_run_argv_path_passes_the_boundary_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import maistro_rsi.candidate_fitness as cf

        seen: dict[str, Any] = {}

        def _fake_run(command: Any, **kwargs: Any) -> _Completed:
            seen.update(kwargs)
            return _Completed()

        monkeypatch.setattr(cf.subprocess, "run", _fake_run)
        cf._run("pytest", Path("."), timeout=5, argv=("python", "-m", "pytest", "-q"))
        assert seen["env"] == candidate_env()
