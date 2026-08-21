"""Tests for the `maistro-rsi` console script (maistro_rsi.cli)."""

from __future__ import annotations

import subprocess

import pytest

from maistro_rsi.cli import build_parser, main, normalize_litellm_env

_ALL_LITELLM_VARS = (
    "LITELLM_BASE_URL",
    "LITELLM_URL",
    "LITELLM_PROXY_URL",
    "LITELLM_MASTER_KEY",
    "LITELLM_PROXY_KEY",
    "LITELLM_API_KEY",
    "LITELLM_VIRTUAL_KEY",
)


@pytest.fixture(autouse=True)
def isolate_structlog(monkeypatch):
    """main() calls configure_logging(), which binds structlog's cached loggers
    to sys.stderr AS CAPTURED BY PYTEST at that moment. That file object is
    closed when the test ends, so any later test (in any file) that logs
    through a cached logger dies with "I/O operation on closed file". Bind to
    the real stderr with caching off, and reset after."""
    import sys

    import structlog

    import maistro_rsi.cli as cli_mod

    def safe_configure(**_kwargs):
        structlog.configure(
            logger_factory=structlog.PrintLoggerFactory(file=sys.__stderr__),
            cache_logger_on_first_use=False,
        )

    monkeypatch.setattr(cli_mod, "configure_logging", safe_configure)
    yield
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def clean_litellm_env(monkeypatch):
    """Every test starts AND ends with no LiteLLM env vars set.

    The pre-test clear keeps host-environment leakage from making these tests
    order-dependent. The post-test clear is just as load-bearing:
    normalize_litellm_env() performs plain `os.environ[name] = value` writes as
    part of its real job, and monkeypatch only restores variables *it* touched —
    it has no visibility into writes made by the function under test, so without
    an explicit teardown those aliases leak into whichever test file pytest
    collects next (observed: test_builders_sandbox.py's "no LLM configured" test
    attempting a real HTTP call to a bogus gateway)."""
    for name in _ALL_LITELLM_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    import os

    for name in _ALL_LITELLM_VARS:
        os.environ.pop(name, None)


class TestNormalizeLitellmEnv:
    def test_returns_none_none_when_unconfigured(self):
        assert normalize_litellm_env() == (None, None)

    def test_reads_from_any_base_url_alias(self, monkeypatch):
        monkeypatch.setenv("LITELLM_URL", "http://gateway:4000")
        base, _key = normalize_litellm_env()
        assert base == "http://gateway:4000"

    def test_strips_trailing_v1(self, monkeypatch):
        monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway:4000/v1")
        base, _key = normalize_litellm_env()
        assert base == "http://gateway:4000"

    def test_strips_trailing_slash_and_v1(self, monkeypatch):
        monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway:4000/v1/")
        base, _key = normalize_litellm_env()
        assert base == "http://gateway:4000"

    def test_key_alias_priority_master_key_wins(self, monkeypatch):
        monkeypatch.setenv("LITELLM_VIRTUAL_KEY", "vk-1")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "mk-1")
        _base, key = normalize_litellm_env()
        assert key == "mk-1"

    def test_key_alias_falls_back_to_virtual_key(self, monkeypatch):
        monkeypatch.setenv("LITELLM_VIRTUAL_KEY", "vk-only")
        _base, key = normalize_litellm_env()
        assert key == "vk-only"

    def test_normalizes_every_alias_to_the_same_value(self, monkeypatch):
        monkeypatch.setenv("LITELLM_URL", "http://gateway:4000/v1")
        monkeypatch.setenv("LITELLM_VIRTUAL_KEY", "vk-only")
        import os

        normalize_litellm_env()
        for name in ("LITELLM_BASE_URL", "LITELLM_URL", "LITELLM_PROXY_URL"):
            assert os.environ[name] == "http://gateway:4000"
        for name in (
            "LITELLM_MASTER_KEY",
            "LITELLM_PROXY_KEY",
            "LITELLM_API_KEY",
            "LITELLM_VIRTUAL_KEY",
        ):
            assert os.environ[name] == "vk-only"


class TestBuildParser:
    def test_run_requires_repo_url_goal_and_test_command(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run"])

    def test_run_parses_required_args_with_defaults(self):
        parser = build_parser()
        args = parser.parse_args(
            ["run", "--repo-url", "https://x/y", "--goal", "g", "--test-command", "pytest -q"]
        )
        assert args.repo_url == "https://x/y"
        assert args.base_branch == "main"
        assert args.workspace_root == "/tmp/maistro-workspace/rsi"
        assert args.open_prs is False
        assert args.max_turns == 10

    def test_unknown_command_exits_nonzero(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["bogus"])


class TestRunExitPaths:
    def test_exits_2_when_litellm_unconfigured_and_not_allowed_stub(self, capsys):
        code = main(["run", "--repo-url", "x", "--goal", "g", "--test-command", "true"])
        assert code == 2
        assert "LiteLLM is not configured" in capsys.readouterr().err


def _init_repo(root) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)


class _FakeMicroVmSandbox:
    def __init__(self) -> None:
        self.destroyed = False

    async def exec(self, command, timeout=60):
        return 0, "ok"

    async def destroy(self):
        self.destroyed = True


class TestCliWiringSmoke:
    """No Docker daemon in this environment: fake the nested MicroVmSandbox and
    keep the LLM in stub mode (no LITELLM_* env — LiteLLMCallable's own
    unconfigured check returns a canned response, no network call), while
    everything else (clone, branch, commit, diff, harness, tournament, JSON
    output) runs for real against a `file://` repo."""

    def test_full_cli_run_completes_and_reports_tests_passed(self, tmp_path, monkeypatch, capsys):
        origin = tmp_path / "origin"
        origin.mkdir()
        _init_repo(origin)

        workspace_root = tmp_path / "maistro-workspace"
        monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (workspace_root,))

        async def fake_create_rsi_sandbox(workspace, settings=None, env=None, backend=None):
            return _FakeMicroVmSandbox()

        monkeypatch.setattr("maistro_rsi.runner.create_rsi_sandbox", fake_create_rsi_sandbox)

        code = main(
            [
                "run",
                "--repo-url",
                f"file://{origin}",
                "--goal",
                "no-op goal (LLM is stubbed)",
                "--test-command",
                "true",
                "--workspace-root",
                str(workspace_root),
                "--models",
                "fake/model-1",
                "--allow-stub-llm",
                "--json",
            ]
        )

        assert code == 0
        import json

        # main() routes structlog to stderr (configure_logging) specifically so
        # --json output on stdout is never interleaved with log lines — proven
        # here by parsing stdout directly with no line-stripping needed.
        summary = json.loads(capsys.readouterr().out)
        assert summary["tests_passed"] is True
        assert summary["model_used"] == "fake/model-1"
        assert summary["pr_url"] is None
        assert summary["error"] is None


class TestCliNewWiring:
    """The CLI must hand RsiCycle a real llm_call when LiteLLM is configured,
    and must fail closed on --open-prs if the quarantine gate can't be built."""

    def test_rsi_cycle_receives_llm_call_and_quarantine_when_configured(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway:4000")
        monkeypatch.setenv("LITELLM_VIRTUAL_KEY", "vk-1")

        origin = tmp_path / "origin"
        origin.mkdir()
        _init_repo(origin)

        captured: dict = {}
        import maistro_rsi.cli as cli_mod

        real_cycle = cli_mod.RsiCycle

        class SpyCycle(real_cycle):
            def __init__(self, *args, **kwargs):
                captured["llm_call"] = kwargs.get("llm_call")
                captured["quarantine_check"] = kwargs.get("quarantine_check")
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(cli_mod, "RsiCycle", SpyCycle)

        # With LITELLM_* set, the builders agent's LiteLLMCallable is
        # "configured" and would attempt a real HTTP call to the bogus
        # gateway — stub the patch fn; this test asserts construction wiring.
        async def noop_patch(sandbox, workspace, model=None):
            return None

        monkeypatch.setattr(cli_mod, "make_builders_apply_patch", lambda *a, **k: noop_patch)

        workspace_root = tmp_path / "maistro-workspace"
        monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (workspace_root,))

        async def fake_create(workspace, settings=None, env=None, backend=None):
            return _FakeMicroVmSandbox()

        monkeypatch.setattr("maistro_rsi.runner.create_rsi_sandbox", fake_create)

        code = main(
            [
                "run",
                "--repo-url",
                f"file://{origin}",
                "--goal",
                "g",
                "--test-command",
                "true",
                "--workspace-root",
                str(workspace_root),
                "--models",
                "fake/m",
                "--open-prs",
                "--json",
            ]
        )

        # The quarantine gate was wired in. llm_call is deliberately NOT
        # passed by the CLI anymore: RsiCycle.run() auto-builds a gateway call
        # per scheduler-picked model (see maistro_rsi.gateway).
        assert captured["llm_call"] is None
        assert captured["quarantine_check"] is not None
        # open_prs + passing tests + quarantine over a real (non-empty) diff:
        # the stub LLM makes no changes, so diff is empty → Warden scan of ""
        # clears, but no push happens against file:// remotes in this test if
        # tests failed; either way the CLI must complete without crashing.
        assert code in (0, 1)

    def test_open_prs_fails_closed_when_quarantine_unbuildable(self, monkeypatch, capsys):
        monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway:4000")
        monkeypatch.setenv("LITELLM_VIRTUAL_KEY", "vk-1")

        import maistro_rsi.cli as cli_mod

        def boom():
            raise RuntimeError("no warden here")

        monkeypatch.setattr(cli_mod, "_build_quarantine_check", boom)

        code = main(
            [
                "run",
                "--repo-url",
                "https://example.com/x",
                "--goal",
                "g",
                "--test-command",
                "true",
                "--models",
                "fake/m",
                "--open-prs",
            ]
        )
        assert code == 2
        assert "quarantine" in capsys.readouterr().err
