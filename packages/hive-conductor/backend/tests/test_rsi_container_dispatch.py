"""The HTTP-initiated cleanup loop runs inside an ephemeral container (#509).

#305 proved the in-process loop cannot be contained: ``python -m pytest`` over
a candidate-edited tree imports that tree's conftest, test modules and plugins
as the Conductor process. #509 therefore dispatches the whole loop — agent,
git, tests, coverage, fitness — into an ephemeral runner container, and these
tests hold that dispatch to its contract:

- the container is real containment: hardened runtime flags, read-only source
  mount, the loop's argv crossing as an argument vector, no shell anywhere;
- the backend attests only what it can actually do (CLI + daemon + image), so
  an unavailable backend refuses the run instead of downgrading to the host;
- cancellation stops the container;
- a container that exits non-zero — or one the backend loses entirely — leaves
  the run ``errored``, not ``running`` forever.

Docker is never contacted: every test drives the same ``_run_docker`` seam the
production code paths use, so a green run here is proven against recorded
argv, not against whatever daemon the CI host happens to have.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["docker"], returncode=returncode, stdout=stdout, stderr="")


class FakeDocker:
    """Records every docker argv the backend builds; scripts the replies.

    Keyed by verb, because the backend's contract with the CLI is verb-shaped:
    ``run`` starts, ``wait`` blocks, ``inspect`` reports, ``info`` probes.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.run_result = _completed(stdout="container-id-1\n")
        self.wait_result = _completed(stdout="0\n")
        self.inspect_result = _completed(stdout="0\n")
        self.info_result = _completed(stdout="ok\n")
        self.image_result = _completed(stdout=runner_image_ref())

    def __call__(self, args: list[str], *, timeout_s: float | None = 60):
        self.calls.append(list(args))
        verb = args[0]
        return {
            "run": self.run_result,
            "wait": self.wait_result,
            "inspect": self.inspect_result,
            "info": self.info_result,
            "image": self.image_result,
            "stop": _completed(stdout=f"{args[-1]}\n"),
        }[verb]


def runner_image_ref() -> str:
    from services.rsi_container_dispatch import DEFAULT_RUNNER_IMAGE

    return DEFAULT_RUNNER_IMAGE


@pytest.fixture
def fake_docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    from services import rsi_container_dispatch as dispatch

    fake = FakeDocker()
    monkeypatch.setattr(dispatch, "_run_docker", fake)
    return fake


@pytest.fixture
def report_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from services import rsi_container_dispatch as dispatch

    root = tmp_path / "runs"
    monkeypatch.setattr(dispatch, "work_root", lambda: root)
    return root


@pytest.fixture
def authorized_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository the deployment has actually authorized."""
    from services import rsi_execution_policy as policy

    repo = tmp_path / "checkout"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(policy, "_authorized_roots", lambda: (tmp_path.resolve(),))
    return repo


def _cleanup_run(run_id: str, repo: Path, **overrides: Any):
    from services.rsi import RunState

    config: dict[str, Any] = {
        "repo_path": str(repo),
        "test_argv": ["python", "-m", "pytest", "-q"],
        "isolation": "container",
        "cycles": 2,
        "fitness": True,
    }
    config.update(overrides)
    return RunState(run_id=run_id, mode="cleanup", config=config)


# ─── the attestation ─────────────────────────────────────────────────────


class TestTheAttestation:
    def test_a_missing_cli_is_named_as_what_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        monkeypatch.setattr(dispatch.shutil, "which", lambda _: None)

        reason = dispatch.unavailability_reason()

        assert reason and "CLI" in reason
        assert dispatch.backend_available() is False

    def test_an_unreachable_daemon_is_named_as_what_is_missing(
        self, fake_docker: FakeDocker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        fake_docker.info_result = _completed(returncode=1)

        reason = dispatch.unavailability_reason()

        assert reason and "daemon" in reason
        assert dispatch.backend_available() is False

    def test_a_missing_runner_image_is_named_with_its_build_command(
        self, fake_docker: FakeDocker
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        fake_docker.image_result = _completed(returncode=1)

        reason = dispatch.unavailability_reason()

        assert reason and "docker build" in reason and dispatch.runner_image() in reason
        assert dispatch.backend_available() is False

    def test_cli_daemon_and_image_present_attests_the_backend(
        self, fake_docker: FakeDocker
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        assert dispatch.backend_available() is True

    def test_the_policy_gate_reads_the_dispatch_attestation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`IN_PROCESS_ISOLATION_AVAILABLE` defaults to None — a gate, not a
        constant. The answer comes from the backend probe, or the probe's
        kill-switch; a literal True would attest containment nobody verified."""
        from services import rsi_container_dispatch as dispatch
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", None)
        monkeypatch.setattr(dispatch, "backend_available", lambda: True)
        assert policy._isolation_available() is True
        assert policy.require_isolation() == policy.REQUIRED_ISOLATION

        monkeypatch.setattr(dispatch, "backend_available", lambda: False)
        assert policy._isolation_available() is False

    def test_the_kill_switch_refuses_even_with_a_live_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_container_dispatch as dispatch
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", False)
        monkeypatch.setattr(dispatch, "backend_available", lambda: True)
        # The refusal explains itself with the backend's reason; keep that
        # probe off the host's real docker too — these tests assert policy
        # plumbing, not daemon state, and a cold daemon must not be able to
        # fail them.
        monkeypatch.setattr(
            dispatch,
            "unavailability_reason",
            lambda: "the docker CLI is not on this process's PATH",
        )

        with pytest.raises(policy.RsiPolicyError, match="no contained RSI backend"):
            policy.require_isolation()

    def test_the_unavailable_refusal_still_names_the_manual_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_container_dispatch as dispatch
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", None)
        monkeypatch.setattr("services.rsi_container_dispatch.backend_available", lambda: False)
        monkeypatch.setattr(
            dispatch,
            "unavailability_reason",
            lambda: "the docker daemon is not reachable from this process",
        )

        with pytest.raises(policy.RsiPolicyError, match=r"run_rsi_isolated\.sh"):
            policy.require_isolation()

    def test_a_hung_docker_probe_is_a_refusal_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The probe is a subprocess conversation with the docker CLI, and a
        hung daemon eats the probe's whole timeout before raising. That must
        land in the same operator-facing refusal as an ordinary "no" — an
        unhandled exception would turn the route's intended 400 into a 500
        that says nothing about what to fix."""
        from services import rsi_container_dispatch as dispatch
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", None)

        def hung(args: list[str], *, timeout_s: float | None = 60) -> Any:
            raise subprocess.TimeoutExpired(cmd=["docker", *args], timeout=timeout_s or 15)

        monkeypatch.setattr(dispatch, "_run_docker", hung)

        with pytest.raises(policy.RsiPolicyError, match="probe itself failed"):
            policy.require_isolation()

    def test_a_backend_probe_that_raises_is_folded_into_the_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The probe is a subprocess conversation, and subprocesses fail in
        two registers: an answer that says no, and an answer that never comes
        (`OSError` when the CLI vanishes between `which` and `run`). Both must
        land in the SAME operator-facing refusal — `_unavailability_reason_safe`
        folds the raising probe into text, so the route's 400 keeps its
        meaning instead of becoming a 500 that says nothing about what to
        fix."""
        from services import rsi_container_dispatch as dispatch
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", None)
        monkeypatch.setattr(dispatch, "backend_available", lambda: False)

        def exploding() -> str:
            raise OSError("the docker CLI vanished between which and run")

        monkeypatch.setattr(dispatch, "unavailability_reason", exploding)

        with pytest.raises(policy.RsiPolicyError, match="probe itself failed"):
            policy.require_isolation()


# ─── the dispatch itself ─────────────────────────────────────────────────


class TestTheLaunchArgv:
    def test_the_loop_runs_in_the_container_not_in_this_process(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        """The whole point of #509, as one argv: the command is docker's, the
        interpreter is the image's venv python, and the loop module it imports
        is the container's — no token of this argv executes here."""
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model="code",
            objective="",
            targets=[],
            use_fitness=True,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        argv = dispatch.container_argv(spec)

        assert argv[0] == "run"  # completed by _run_docker's "docker" prefix
        image_at = argv.index(dispatch.runner_image())
        loop_cmd = argv[image_at + 1 :]
        assert loop_cmd[:4] == ["/workspace/.venv/bin/python", "-m", "maistro_rsi", "run"]
        assert "--repo" in loop_cmd and loop_cmd[loop_cmd.index("--repo") + 1] == "/target"
        # The loop's interpreter finds the workspace source the way the wrapper
        # provides it (baked source + PYTHONPATH; maistro-rsi is an optional
        # workspace member, absent from the image's `uv sync`), and git reads
        # its safe.directory allowance from the global config `launch()` writes
        # into the report mount — the clone-time ownership check ignores
        # command-line-scoped config.
        assert f"PYTHONPATH={dispatch.PYTHONPATH_IN_CONTAINER}" in argv
        assert (
            f"GIT_CONFIG_GLOBAL={dispatch.REPORT_MOUNT_TARGET}/{dispatch.GIT_CONFIG_FILENAME}"
            in argv
        )

    def test_no_shell_token_anywhere_in_the_launch_argv(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model="code",
            objective="explain; $(id) `id`",
            targets=[],
            use_fitness=True,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        argv = dispatch.container_argv(spec)

        # A metacharacter in a free-text field (the objective, a model name)
        # is a character in an argv token, not shell source — there is no
        # shell on either side of this boundary to interpret it.
        assert not any(Path(token).name in {"sh", "bash", "dash", "zsh"} for token in argv)
        assert "bash" not in argv and "-lc" not in argv

    def test_the_source_repo_is_mounted_read_only(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        """The loop clones its target and never writes to it, so the mount
        can be read-only — which makes the authorized checkout one thing no
        candidate edit can reach through the container."""
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        argv = dispatch.container_argv(spec)

        assert "/srv/repos/checkout:/target:ro" in argv

    def test_the_report_dir_is_mounted_outside_the_edited_tree(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        """The wrapper's rule: REPORT_DIR is not under /workspace, so the
        workspace-rooted agent tools can neither read nor write the reports —
        and here the image's own toolchain keeps /workspace."""
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        argv = dispatch.container_argv(spec)

        assert f"{spec.report_dir}:/run/reports" in argv

    def test_the_policy_argv_is_forwarded_as_a_vector(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        loop_cmd = dispatch.container_argv(spec)
        argv_at = loop_cmd.index("--test-argv")

        # A bare `python` is resolved to the image's virtualenv interpreter
        # before forwarding: the base env's pinned PATH would otherwise pick
        # the base-image interpreter, which cannot import pytest (Codex, #509).
        assert json.loads(loop_cmd[argv_at + 1]) == [
            "/workspace/.venv/bin/python",
            "-m",
            "pytest",
            "-q",
        ]

    def test_an_argument_that_merely_says_python_is_not_rewritten(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        """Only the leading token is the executable; candidate data that says
        `python` must pass through untouched."""
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("/opt/interpreter/python3", "-m", "pytest", "-q"),
            cycles=1,
            agent_turns=1,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        loop_cmd = dispatch.container_argv(spec)
        argv_at = loop_cmd.index("--test-argv")

        assert json.loads(loop_cmd[argv_at + 1]) == [
            "/opt/interpreter/python3",
            "-m",
            "pytest",
            "-q",
        ]

    def test_the_container_side_command_parses_with_the_real_cli(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        """The strongest host-side proof available without a daemon: the loop
        command the dispatch builds is accepted by the real `maistro_rsi`
        argparse parser, and the vector it carries is the one that would run.

        The loop's CLI requires `--test-cmd`, and a dispatch that omitted it
        would fail every run at exit 2 inside the container — before a single
        cycle — which the run record would only ever show as a non-zero exit.
        The parsed result also pins the containment-relevant fields: the repo
        is the read-only mount and `--test-argv` wins over the display-only
        `--test-cmd` in `LocalRsiLoop._run_tests` (#305)."""
        from services import rsi_container_dispatch as dispatch

        from maistro_rsi.__main__ import _build_parser

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model="code",
            objective="tighten the module",
            targets=["pkg/a.py"],
            use_fitness=True,
            coverage_source="src",
            coverage_pytest_args="-k fast",
            scout=True,
            genome_models=["devstral", "codestral"],
            roster_size=5,
        )

        argv = dispatch.container_argv(spec)
        loop_cmd = argv[argv.index(dispatch.runner_image()) + 1 :]

        # loop_cmd is [interpreter, "-m", "maistro_rsi", "run", *flags]; the
        # parser consumes from "run" on.
        args = _build_parser().parse_args(loop_cmd[3:])

        assert args.command == "run"
        assert args.repo == "/target"
        assert args.report_dir == "/run/reports"
        assert args.work_root == "/tmp/rsi-work"  # nosec B108 — asserts the pinned container-internal constant, not a host path
        assert json.loads(args.test_argv) == [
            "/workspace/.venv/bin/python",
            "-m",
            "pytest",
            "-q",
        ]
        # Display form mirrors the resolved vector; still never executed.
        assert args.test_cmd == "/workspace/.venv/bin/python -m pytest -q"
        assert args.fitness is True
        assert args.cycles == 3
        assert args.agent_turns == 6
        assert args.model == "code"
        assert args.objective == "tighten the module"
        assert args.targets == "pkg/a.py"
        assert args.coverage_source == "src"
        assert args.coverage_pytest_args == "-k fast"
        assert args.scout is True
        assert args.genome_models == "devstral,codestral"
        assert args.roster_size == 5

    def test_the_runtime_is_hardened_like_the_wrapper(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        argv = dispatch.container_argv(spec)

        assert "--cap-drop=ALL" in argv
        assert "--security-opt=no-new-privileges" in argv
        assert "--pids-limit" in argv
        assert "--memory" in argv
        assert "--rm" in argv  # ephemeral: the container removes itself
        # The loop runs as THIS process's uid:gid (POSIX): with every
        # capability stripped, root could not write the host-owned report
        # mount, and the loop needs no privilege inside the container.
        if hasattr(os, "getuid"):
            assert "--user" in argv
            assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"

    def test_the_container_is_labeled_with_its_run_id(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=3,
            agent_turns=6,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        argv = dispatch.container_argv(spec)

        assert "maistro.rsi.run-id=abc123" in argv
        assert "rsi-run-abc123" in argv


# ─── the service lifecycle ───────────────────────────────────────────────


class TestTheDispatchedLifecycle:
    def _service(self) -> Any:
        from services.rsi import _RsiService

        svc = _RsiService()
        svc.poll_interval_s = 0.01
        return svc

    def test_a_run_starts_and_is_contained(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The success path the Start button needs: policy in, contained run
        out — and the in-process loop demonstrably never constructed."""

        import maistro_rsi.local_loop as local_loop

        def _no_host_loop(*_a: object, **_kw: object) -> None:
            raise AssertionError("the loop must not run in the Conductor process")

        monkeypatch.setattr(local_loop, "LocalRsiLoop", _no_host_loop)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        asyncio.run(svc._drive(run))

        assert run.status == "completed"
        assert run.container_id == "container-id-1"
        assert run.report_dir is not None and "abc123" in run.report_dir
        # The only host subprocesses were docker verbs; none executed a
        # command string, and none of them is the loop.
        verbs = [call[0] for call in fake_docker.calls]
        assert verbs == ["run", "wait", "inspect"] or set(verbs) <= {"run", "wait", "inspect"}
        assert all(call[1] != "exec" for call in fake_docker.calls)
        # launch() staged the container's global git config into the mounted
        # report dir: exactly the read-only mount target and its gitdir.
        gitconfig = (report_root / "rsi-abc123" / "reports" / "gitconfig").read_text(
            encoding="utf-8"
        )
        assert "directory = /target\n" in gitconfig
        assert "directory = /target/.git\n" in gitconfig
        assert "*" not in gitconfig

    def test_the_run_refuses_when_the_backend_cannot_attest(
        self, admin_client, authorized_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unavailable backend is a refusal, not a downgrade to the host —
        and the refusal says which piece is missing."""
        from services import rsi_container_dispatch as dispatch
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", None)
        monkeypatch.setattr(
            dispatch,
            "unavailability_reason",
            lambda: "the docker daemon is not reachable from this process",
        )

        def _no_launch(spec: object) -> str:
            raise AssertionError("a refused run must not launch a container")

        monkeypatch.setattr(dispatch, "launch", _no_launch)

        response = admin_client.post(
            "/v1/rsi/runs",
            json={"mode": "cleanup", "repo_path": str(authorized_repo), "test_profile": "pytest"},
        )

        assert response.status_code == 400
        assert "no contained RSI backend" in response.json()["detail"]
        assert "docker daemon" in response.json()["detail"]

    def test_cancellation_stops_the_container(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stopping a dispatched run is a docker stop — a different operation
        from cancelling an asyncio task, and the test proves both happen."""
        from services import rsi_container_dispatch as dispatch

        started = threading.Event()
        release = threading.Event()
        stopped: list[str] = []

        def fake_wait(container_id: str) -> int:
            started.set()
            release.wait(10)
            return 0

        def fake_stop(container_id: str) -> bool:
            stopped.append(container_id)
            release.set()
            return True

        monkeypatch.setattr(dispatch, "wait", fake_wait)
        monkeypatch.setattr(dispatch, "stop_container", fake_stop)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        svc._runs[run.run_id] = run

        async def scenario() -> None:
            run.task = asyncio.ensure_future(svc._drive(run))
            await asyncio.to_thread(started.wait, 10)
            assert svc.stop_run(run.run_id) is True
            await asyncio.gather(run.task, return_exceptions=True)

        asyncio.run(scenario())

        assert stopped == ["container-id-1"]
        assert run.status == "stopped"
        assert run.container_id == "container-id-1"

    def test_a_stop_that_races_the_launch_stops_what_launch_started(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`docker run` happens in a thread cancellation cannot interrupt: a
        stop that arrives mid-launch sees no container_id, yet the container
        still gets started a moment later. The cleanup must wait out the
        bounded launch and stop whatever it actually started."""
        from services import rsi_container_dispatch as dispatch

        launched = threading.Event()
        release = threading.Event()
        stopped: list[str] = []

        def fake_launch(spec: object) -> str:
            launched.set()
            release.wait(10)
            return "container-id-1"

        def fake_stop(container_id: str) -> bool:
            stopped.append(container_id)
            return True

        monkeypatch.setattr(dispatch, "launch", fake_launch)
        monkeypatch.setattr(dispatch, "stop_container", fake_stop)

        def fail_if_waited(container_id: str) -> int:
            raise AssertionError("a cancelled launch must not reach the wait")

        monkeypatch.setattr(dispatch, "wait", fail_if_waited)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        svc._runs[run.run_id] = run

        async def scenario() -> None:
            run.task = asyncio.ensure_future(svc._drive(run))
            await asyncio.to_thread(launched.wait, 10)
            assert run.container_id is None
            assert svc.stop_run(run.run_id) is True
            release.set()
            await asyncio.gather(run.task, return_exceptions=True)

        asyncio.run(scenario())

        assert stopped == ["container-id-1"]
        assert run.status == "stopped"
        assert run.container_id == "container-id-1"

    def test_a_container_that_exits_non_zero_is_reported_errored(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        fake_docker.wait_result = _completed(stdout="1\n")
        monkeypatch.setattr(dispatch, "wait", lambda cid: 1)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        asyncio.run(svc._drive(run))

        assert run.status == "errored"
        assert run.last_error is not None
        assert "exited with code 1" in run.last_error

    def test_a_container_the_backend_loses_is_reported_errored(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A daemon restart can take the container (and `docker wait`) with
        it. The run must land errored, not running forever."""
        from services import rsi_container_dispatch as dispatch

        def fake_wait(container_id: str) -> int:
            raise dispatch.DispatchError("lost contact with the runner container ()")

        monkeypatch.setattr(dispatch, "wait", fake_wait)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        asyncio.run(svc._drive(run))

        assert run.status == "errored"
        assert run.last_error and "lost contact" in run.last_error

    def test_checkpoints_written_by_the_container_become_run_progress(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The report mount is the only channel back: cycles and promotions
          the loop writes into /run/reports must reach the run record the UI
        polls."""

        report_dir = report_root / "rsi-abc123" / "reports"
        report_dir.mkdir(parents=True)
        (report_dir / "checkpoint-3.json").write_text(
            json.dumps({"cycles_run": 3, "promotions": 1}), encoding="utf-8"
        )

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        asyncio.run(svc._drive(run))

        assert run.status == "completed"
        assert run.cycles == 3
        assert run.promotions == 1
        assert run.summary and "1 promotion(s) across 3 cycle(s)" in run.summary
        assert run.export_dir == str(report_dir / "export")

    def test_a_launch_failure_marks_the_run_errored(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        def refuse_launch(spec: object) -> str:
            raise dispatch.DispatchError("docker refused the run request (exit 125): no such image")

        monkeypatch.setattr(dispatch, "launch", refuse_launch)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        asyncio.run(svc._drive(run))

        assert run.status == "errored"
        assert run.container_id is None
        assert "docker refused the run request" in (run.last_error or "")

    def test_stop_run_survives_a_failed_container_stop(
        self,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`docker stop` itself can fail — daemon gone mid-request — and that
        must not stop the RUN from stopping: the record still settles and the
        task is still cancelled."""
        from services import rsi_container_dispatch as dispatch

        def failing_stop(container_id: str) -> bool:
            raise OSError("the docker daemon went away mid-stop")

        monkeypatch.setattr(dispatch, "stop_container", failing_stop)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        run.container_id = "container-id-1"
        svc._runs[run.run_id] = run

        async def scenario() -> None:
            async def hang() -> None:
                await asyncio.Event().wait()

            run.task = asyncio.ensure_future(hang())
            assert svc.stop_run(run.run_id) is True
            await asyncio.gather(run.task, return_exceptions=True)

        asyncio.run(scenario())

        assert run.status == "stopped"
        assert run.container_id == "container-id-1"

    def test_stop_run_treats_an_already_gone_container_as_stopped(
        self,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """False from the stop means "it was already gone" — success by
        another name for cancellation, so the run still settles stopped."""
        from services import rsi_container_dispatch as dispatch

        monkeypatch.setattr(dispatch, "stop_container", lambda _cid: False)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        run.container_id = "container-id-1"
        svc._runs[run.run_id] = run

        async def scenario() -> None:
            async def hang() -> None:
                await asyncio.Event().wait()

            run.task = asyncio.ensure_future(hang())
            assert svc.stop_run(run.run_id) is True
            await asyncio.gather(run.task, return_exceptions=True)

        asyncio.run(scenario())

        assert run.status == "stopped"

    def test_a_cancelled_launch_that_fails_stops_nothing(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The mid-launch cleanup waits out the bounded launch — and when the
        launch that finally lands FAILED, there is no container to stop, and
        the cleanup must not pretend there was one."""
        from services import rsi_container_dispatch as dispatch

        launched = threading.Event()
        release = threading.Event()
        stops: list[str] = []

        def fake_launch(spec: object) -> str:
            launched.set()
            release.wait(10)
            raise dispatch.DispatchError("docker refused the run request (exit 125): gone")

        monkeypatch.setattr(dispatch, "launch", fake_launch)

        def record_stop(container_id: str) -> bool:
            stops.append(container_id)
            return True

        monkeypatch.setattr(dispatch, "stop_container", record_stop)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        svc._runs[run.run_id] = run

        async def scenario() -> None:
            run.task = asyncio.ensure_future(svc._drive(run))
            await asyncio.to_thread(launched.wait, 10)
            run.task.cancel()
            release.set()
            await asyncio.gather(run.task, return_exceptions=True)

        asyncio.run(scenario())

        assert stops == []
        assert run.container_id is None
        assert run.status == "stopped"
        assert fake_docker.calls == []  # no wait, no inspect, no stop

    def test_a_cancellation_the_container_survives_is_logged_not_masked(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        authorized_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A cancellation that did NOT go through stop_run (a task cancel on
        a run whose container is already known) stops its container too — and
        when that stop fails, the cancellation still propagates instead of
        being masked by the cleanup's own failure."""
        from services import rsi_container_dispatch as dispatch

        started = threading.Event()
        release = threading.Event()

        def fake_wait(container_id: str) -> int:
            started.set()
            release.wait(10)
            return 0

        def failing_stop(container_id: str) -> bool:
            raise OSError("the docker daemon went away mid-stop")

        monkeypatch.setattr(dispatch, "wait", fake_wait)
        monkeypatch.setattr(dispatch, "stop_container", failing_stop)

        svc = self._service()
        run = _cleanup_run("abc123", authorized_repo)
        svc._runs[run.run_id] = run

        async def scenario() -> None:
            run.task = asyncio.ensure_future(svc._drive(run))
            await asyncio.to_thread(started.wait, 10)
            run.task.cancel()  # direct cancel: no stop_run has run yet
            release.set()
            await asyncio.gather(run.task, return_exceptions=True)

        asyncio.run(scenario())

        assert run.status == "stopped"
        assert run.container_id == "container-id-1"

    def test_a_greenfield_run_is_refused_when_the_package_is_absent(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 503 the UI reads when maistro-rsi is not importable in this
        process. Only cleanup is dispatched (#509); the greenfield tournament
        still needs the package here, so its gate stays."""
        from services import rsi as rsi_service

        monkeypatch.setattr(rsi_service, "_rsi_available", lambda: False)

        response = admin_client.post(
            "/v1/rsi/runs", json={"mode": "greenfield", "repo_path": "/srv/repos/checkout"}
        )

        assert response.status_code == 503
        assert "maistro-rsi is not installed" in response.json()["detail"]

    def test_the_spec_derives_outputs_from_the_run_id(
        self, report_root: Path, authorized_repo: Path
    ) -> None:
        """Output directories stay server-derived (#305): the request cannot
        aim the loop's writes, and two runs cannot collide."""
        from services import rsi_container_dispatch as dispatch

        spec = dispatch.build_spec(
            run_id="abc123",
            repo=authorized_repo,
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=1,
            agent_turns=6,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

        assert spec.report_dir == report_root / "rsi-abc123" / "reports"
        assert str(authorized_repo) not in str(spec.report_dir)


# ─── the docker seam, the gateway plumbing, and the CLI failure modes ────


class TestTheDockerSeamAndGatewayPlumbing:
    """The pieces the lifecycle tests drive through fakes, held to their own
    contracts: the one place a docker process is born, the env entries that
    cross the container boundary, and the network the container joins."""

    def _spec(self, report_root: Path) -> Any:
        from services import rsi_container_dispatch as dispatch

        return dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=1,
            agent_turns=1,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

    def test_run_docker_executes_the_docker_cli_as_an_argv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_run_docker` is the seam every other test fakes. It must speak to
        the CLI as an argument vector — there is no shell on this side of the
        boundary to interpret one — and return the CLI's answer verbatim."""
        shim_dir = tmp_path / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "docker"
        shim.write_text('#!/bin/sh\necho "argv=$*"\n', encoding="utf-8")
        shim.chmod(0o755)
        monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}")

        from services import rsi_container_dispatch as dispatch

        probe = dispatch._run_docker(["info", "--format", "ok"], timeout_s=15)

        assert probe.returncode == 0
        assert probe.stdout == "argv=info --format ok\n"

    def test_the_user_pin_degrades_gracefully_without_a_uid_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No uid model (Windows), no `--user` flag — the mount-writability
        fix is POSIX-only by construction, and its absence must be quiet."""
        from services import rsi_container_dispatch as dispatch

        monkeypatch.delattr(os, "getuid", raising=False)

        assert dispatch._container_user() == []

    def test_only_the_named_gateway_credentials_cross_the_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
        monkeypatch.setenv("LITELLM_API_KEY", "sk-api")
        monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)

        assert dispatch._gateway_credentials() == [
            "LITELLM_MASTER_KEY=sk-master",
            "LITELLM_API_KEY=sk-api",
        ]

    def test_the_gateway_credentials_reach_the_container_as_env_entries(
        self,
        fake_docker: FakeDocker,
        report_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
        monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)

        argv = dispatch.container_argv(self._spec(report_root))

        key_at = argv.index("LITELLM_MASTER_KEY=sk-master")
        assert argv[key_at - 1] == "-e"

    def test_the_gateway_network_falls_back_to_the_default_bridge(
        self, fake_docker: FakeDocker
    ) -> None:
        """A gateway container that answers nothing to `inspect` still leaves
        the run launchable: it joins the default bridge and reaches the
        gateway through the published host-loopback route instead."""
        from services import rsi_container_dispatch as dispatch

        fake_docker.inspect_result = _completed(stdout="")

        assert dispatch._detect_gateway_network() == "bridge"


class TestTheLaunchFailureModes:
    """`launch` raises DispatchError, never a bare subprocess exception —
    the run record shows an operator-facing summary, not a traceback."""

    def _spec(self, report_root: Path) -> Any:
        from services import rsi_container_dispatch as dispatch

        return dispatch.build_spec(
            run_id="abc123",
            repo=Path("/srv/repos/checkout"),
            test_argv=("python", "-m", "pytest", "-q"),
            cycles=1,
            agent_turns=1,
            model=None,
            objective="",
            targets=[],
            use_fitness=False,
            coverage_source=".",
            coverage_pytest_args="",
            scout=False,
            genome_models=[],
            roster_size=4,
        )

    def test_a_timed_out_run_request_is_a_dispatch_error(
        self, report_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        def hung(args: list[str], *, timeout_s: float | None = 60) -> Any:
            if args[0] != "run":
                # The network probe inside container_argv still answers; only
                # the run request itself hangs.
                return _completed(stdout="bridge\n")
            raise subprocess.TimeoutExpired(cmd=["docker", *args], timeout=timeout_s or 120)

        monkeypatch.setattr(dispatch, "_run_docker", hung)

        with pytest.raises(dispatch.DispatchError, match="did not answer the run request"):
            dispatch.launch(self._spec(report_root))

    def test_a_refused_run_request_carries_the_cli_stderr(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        fake_docker.run_result = _completed(returncode=125)

        with pytest.raises(
            dispatch.DispatchError, match=r"docker refused the run request \(exit 125\)"
        ):
            dispatch.launch(self._spec(report_root))

    def test_a_run_without_a_container_id_is_a_dispatch_error(
        self, fake_docker: FakeDocker, report_root: Path
    ) -> None:
        """Docker exiting 0 while printing no id would otherwise hand the
        service an empty container_id and a run nothing could ever stop."""
        from services import rsi_container_dispatch as dispatch

        fake_docker.run_result = _completed(stdout="")

        with pytest.raises(dispatch.DispatchError, match="started no container"):
            dispatch.launch(self._spec(report_root))


class TestStopWaitAndInspect:
    """The verbs cancellation and the wait loop are built on, driven against
    the same `_run_docker` seam, so their contract holds without a daemon."""

    def test_stop_runs_one_bounded_stop(self, fake_docker: FakeDocker) -> None:
        from services import rsi_container_dispatch as dispatch

        assert dispatch.stop_container("cid-7") is True
        assert fake_docker.calls[-1] == [
            "stop",
            "--time",
            str(dispatch.STOP_TIMEOUT_S),
            "cid-7",
        ]

    def test_an_already_gone_container_stops_as_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        monkeypatch.setattr(
            dispatch, "_run_docker", lambda a, *, timeout_s=60: _completed(returncode=1)
        )

        assert dispatch.stop_container("cid-7") is False

    def test_a_wedged_stop_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A stop that times out means the container is wedged, not
        unkillable — the caller treats a timeout as stop-issued and the
        wait still reaps the exit code when the container eventually dies."""
        from services import rsi_container_dispatch as dispatch

        def hung(args: list[str], *, timeout_s: float | None = 60) -> Any:
            raise subprocess.TimeoutExpired(cmd=["docker", *args], timeout=timeout_s or 50)

        monkeypatch.setattr(dispatch, "_run_docker", hung)

        assert dispatch.stop_container("cid-7") is True

    def test_wait_returns_the_exit_code_the_cli_prints(self, fake_docker: FakeDocker) -> None:
        from services import rsi_container_dispatch as dispatch

        fake_docker.wait_result = _completed(stdout="7\n")

        assert dispatch.wait("cid-7") == 7

    def test_wait_falls_back_to_inspect_when_the_cli_prints_no_code(
        self, fake_docker: FakeDocker
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        fake_docker.wait_result = _completed(stdout="")
        fake_docker.inspect_result = _completed(stdout="3\n")

        assert dispatch.wait("cid-7") == 3

    def test_a_container_the_backend_cannot_see_anywhere_is_a_dispatch_error(
        self, fake_docker: FakeDocker
    ) -> None:
        """Neither `wait` nor `inspect` can answer: the run must surface
        DispatchError — the service reports it errored rather than leaving
        it running forever against a container that no longer exists."""
        from services import rsi_container_dispatch as dispatch

        fake_docker.wait_result = _completed(returncode=1)
        fake_docker.inspect_result = _completed(returncode=1)

        with pytest.raises(dispatch.DispatchError, match="lost contact"):
            dispatch.wait("cid-7")

    def test_inspect_answers_none_when_the_state_is_not_an_exit_code(
        self, fake_docker: FakeDocker
    ) -> None:
        from services import rsi_container_dispatch as dispatch

        fake_docker.inspect_result = _completed(stdout="running\n")

        assert dispatch._inspect_exit_code("cid-7") is None


class TestTheReportChannel:
    """Checkpoints in the mounted report dir are the only channel run
    progress crosses back through. The poller must survive everything a
    container can write — or fail to write — into that directory."""

    def test_a_missing_report_dir_is_no_progress(self, tmp_path: Path) -> None:
        from services import rsi_container_dispatch as dispatch

        assert dispatch.poll_reports(tmp_path / "absent") == {}

    def test_a_corrupt_or_non_object_checkpoint_falls_back_to_the_newest_readable(
        self, tmp_path: Path
    ) -> None:
        """A half-written newest checkpoint (the container died mid-write) or
        a JSON array where an object belongs is skipped, not reported as
        zeros and not fatal."""
        import json as _json

        (tmp_path / "checkpoint-9.json").write_text("{not json", encoding="utf-8")
        (tmp_path / "checkpoint-8.json").write_text(_json.dumps(["nope"]), encoding="utf-8")
        (tmp_path / "checkpoint-4.json").write_text(
            _json.dumps({"cycles_run": 4, "promotions": 1}), encoding="utf-8"
        )

        from services import rsi_container_dispatch as dispatch

        assert dispatch.poll_reports(tmp_path) == {"cycles_run": 4, "promotions": 1}

    def test_an_older_or_shapeless_checkpoint_never_rolls_progress_back(
        self, tmp_path: Path
    ) -> None:
        import json as _json

        (tmp_path / "checkpoint-1.json").write_text(
            _json.dumps({"cycles_run": 5, "promotions": 2}), encoding="utf-8"
        )
        (tmp_path / "checkpoint-2.json").write_text(
            _json.dumps({"cycles_run": 2, "promotions": 9}), encoding="utf-8"
        )
        (tmp_path / "checkpoint-3.json").write_text(
            _json.dumps({"promotions": 3}),
            encoding="utf-8",  # no cycles_run
        )

        from services import rsi_container_dispatch as dispatch

        assert dispatch.poll_reports(tmp_path) == {"cycles_run": 5, "promotions": 2}
