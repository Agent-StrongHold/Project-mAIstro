"""Signal-level integration tests — SIGTERM drains through lifespan shutdown.

Evidence for #819: `maistro_server.main` used to install its own SIGTERM/SIGINT
handler during lifespan startup, which *replaced* Uvicorn's `handle_exit`.
`should_exit` was then never set: the server ignored SIGTERM, the lifespan
shutdown block (task drain, sandbox cleanup, shared-client close, DB engine
disposal) never ran, and a container's grace deadline ended in SIGKILL with
sandboxes and pooled connections still live.

These tests drive real OS signals against real server processes (subprocesses
of `maistro_server.main:app` under Uvicorn — the shape `entrypoint.py` runs)
and assert the post-#819 contract:

- Uvicorn remains the process-exit signal authority (AC-1);
- SIGTERM reaches MAIstro's lifespan shutdown callbacks (AC-2);
- graceful termination leaves no MAIstro-owned sandbox containers orphaned,
  and the server restarts cleanly (AC-3);
- an in-flight task drain is bounded, cancels to a failure state, and still
  lets the process exit normally (AC-4).

The subprocesses need no PostgreSQL, Redis or LLM: the app boots its in-memory
spine (`run_store_in_process_only`), and the one seam the tests substitute —
`conductor.run_task`, which `main`'s `runner_executor` calls and `TaskRunner`
is constructed around — is the package's own injection point. Sandbox workspaces resolve under
`tempfile.gettempdir()/maistro-workspace`, which
`maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS` already allowlists.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Generous exit deadline. After SIGTERM the server drains (bounded by
#: SHUTDOWN_DRAIN_TIMEOUT, which the drain test shrinks via the driver), then
#: runs sandbox cleanup — whose lazy `fastmcp` import alone can take tens of
#: seconds on a cold interpreter. The deadline proves the process *does* exit;
#: it is not a grace-period extension of the defect.
_EXIT_DEADLINE_S = 90.0

_SANDBOX_IMAGE = "python:3.12-slim"


def _clean_signal_exit(rc: int | None) -> bool:
    """A graceful, signal-driven stop may report either exit status.

    Uvicorn runs the full graceful shutdown, then — by design — re-raises the
    captured signal after restoring the default handlers (uvicorn/server.py,
    `capture_signals`), so a supervisor observing the process sees the
    conventional "died of SIGTERM" status instead of exit 0. Both statuses
    mean the same thing here: every lifespan shutdown callback ran to the end
    before the process left. Anything else (another signal, another code) is
    not a clean stop.
    """
    return rc == 0 or rc == -signal.SIGTERM


def _server_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env for a server subprocess: in-memory spine, auth off, info logs.

    DEBUG=true matters for the assertions: `configure_logging(debug=False)`
    filters structlog at WARNING, which would hide the `maistro_engine_stopped`
    / `task_runner_draining` / `all_sandboxes_cleaned_up` info events these
    tests read as shutdown-callback evidence.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("DB_") and key not in ("DATABASE_URL", "API_KEYS", "ROUTER_API_KEY")
    }
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(_REPO_ROOT / "packages" / "maistro-core" / "src"),
            str(_REPO_ROOT / "packages" / "maistro-server" / "src"),
            env.get("PYTHONPATH", ""),
        )
    )
    env.update(
        {
            "ROUTER_API_KEY": "sigterm-test-router-key",
            # Startup validates API_KEY identities even when auth is disabled.
            "API_KEYS": '["sigterm-test:sigterm-test-api-key"]',
            "REQUIRE_AUTH": "false",
            "DEBUG": "true",
        }
    )
    if extra:
        env.update(extra)
    return env


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_open(port: int, timeout_s: float = 0.5) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout_s)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _spawn(code: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )


def _wait_ready(proc: subprocess.Popen[str], port: int, timeout_s: float = 60.0) -> None:
    """Wait until the server accepts TCP connections or the process dies."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
            raise AssertionError(f"server process died during startup:\n{output[-4000:]}")
        if _port_open(port):
            return
        time.sleep(0.2)
    proc.kill()
    raise AssertionError(f"server not accepting connections after {timeout_s:g}s")


def _sigterm_and_wait(
    proc: subprocess.Popen[str], deadline_s: float = _EXIT_DEADLINE_S
) -> tuple[int | None, float, str]:
    """SIGTERM the process; return (returncode, elapsed_s, remaining output)."""
    proc.send_signal(signal.SIGTERM)
    started = time.monotonic()
    deadline = started + deadline_s
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            rest = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
            return rc, time.monotonic() - started, rest
        time.sleep(0.2)
    return None, time.monotonic() - started, ""


def _submit_task(port: int, workspace: str, timeout_s: float = 15.0) -> str:
    """Admit one task through the real HTTP door; return its task_id."""
    payload = json.dumps({"description": "sigterm drain test", "workspace": workspace}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/tasks",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer sigterm-test-api-key",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        body = json.loads(response.read())
        assert response.status == 202, body
        return str(body["task_id"])


def _get_task(port: int, task_id: str, timeout_s: float = 15.0) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/tasks/{task_id}",
        headers={"Authorization": "Bearer sigterm-test-api-key"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return dict(json.loads(response.read()))


def _docker_ready() -> bool:
    """Same gate as packages/maistro-bootstrap/tests/test_container_sandbox.py."""
    if shutil.which("docker") is None:
        return False
    return (
        subprocess.run(
            ["docker", "image", "inspect", _SANDBOX_IMAGE],
            capture_output=True,
            timeout=60,
        ).returncode
        == 0
    )


def _maistro_sandbox_containers() -> list[str]:
    """Names of MAIstro-owned sandbox containers (created or exited)."""
    completed = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", "name=maistro-sandbox-"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return [name for name in completed.stdout.splitlines() if name.strip()]


def _container_exists(container_id: str) -> bool:
    return (
        subprocess.run(
            ["docker", "inspect", container_id],
            capture_output=True,
            timeout=60,
        ).returncode
        == 0
    )


@pytest.fixture()
def workspace_root() -> Iterator[Path]:
    """Sandbox workspace root under the platform temp dir (an allowed root)."""
    root = Path(tempfile.gettempdir()) / "maistro-workspace" / "sigterm-819"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


class TestSigtermReachesLifespanShutdown:
    """AC-1/AC-2 — SIGTERM terminates the process through lifespan shutdown."""

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_sigterm_terminates_server_and_runs_shutdown_callbacks(
        self, tmp_path: Path
    ) -> None:
        port = _free_port()
        proc = _spawn(
            f"""
            import asyncio, uvicorn
            from maistro_server.main import app
            config = uvicorn.Config(app, host="127.0.0.1", port={port}, log_level="info")
            asyncio.run(uvicorn.Server(config).serve())
            """,
            _server_env(),
        )
        try:
            _wait_ready(proc, port)
            rc, elapsed, output = _sigterm_and_wait(proc)
        finally:
            if proc.poll() is None:
                proc.kill()

        assert rc is not None, (
            f"process still alive {_EXIT_DEADLINE_S:g}s after SIGTERM — the #819 defect: "
            "Uvicorn never saw should_exit, so lifespan shutdown never ran"
        )
        assert _clean_signal_exit(rc), f"expected clean exit, got rc={rc}\n{output[-4000:]}"
        # Uvicorn ran the lifespan shutdown half ...
        assert "Application shutdown complete" in output
        # ... and MAIstro's own shutdown block ran to its final callback —
        # sandbox cleanup then shared-client close then engine disposal, after
        # the runner drained.
        assert "maistro_engine_stopped" in output, (
            f"lifespan shutdown did not reach its final callback:\n{output[-4000:]}"
        )
        assert "all_sandboxes_cleaned_up" in output
        # The drain itself may be instant on an idle server, but the bounded
        # handoff must still be visible.
        assert "task_runner_stopped" in output
        assert elapsed < _EXIT_DEADLINE_S


class TestSigtermDrainsInflightTask:
    """AC-4 — in-flight drain is bounded, fails the task, and still exits."""

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_sigterm_drains_bounded_marks_failure_and_exits(
        self, tmp_path: Path, workspace_root: Path
    ) -> None:
        port = _free_port()
        started_marker = tmp_path / "executor-started"
        drain_timeout_s = 3.0
        rc: int | None = None

        # The driver shrinks SHUTDOWN_DRAIN_TIMEOUT so the bounded wait is
        # observable without burning a real 30s, and swaps the executor for one
        # that never finishes — the same seam TaskRunner is constructed with.
        proc = _spawn(
            f"""
            import asyncio, sys
            from pathlib import Path

            async def _unfinished(request, **_authority):
                # `main.runner_executor` calls `conductor.run_task` with the
                # Container's governed egress and the workspace/project it was
                # built for (#718). A stub that takes only the request raises
                # TypeError before it can write the marker, and the drain this
                # test is about never gets an in-flight task to drain. The
                # kwargs are swallowed on purpose: what crosses that seam is
                # #718's contract to assert, not this test's.
                Path({str(started_marker)!r}).write_text("started")
                await asyncio.Event().wait()

            import maistro.agents.conductor as conductor
            conductor.run_task = _unfinished

            import maistro_server.main as main
            main.SHUTDOWN_DRAIN_TIMEOUT = {drain_timeout_s}

            import uvicorn
            config = uvicorn.Config(main.app, host="127.0.0.1", port={port}, log_level="info")
            asyncio.run(uvicorn.Server(config).serve())
            """,
            _server_env(),
        )
        try:
            _wait_ready(proc, port)
            workspace = str(workspace_root / "drain" / "ws")
            task_id = _submit_task(port, workspace)

            # The task must actually be in flight before SIGTERM: the marker
            # is written by the executor itself.
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline and not started_marker.exists():
                if proc.poll() is not None:
                    output = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
                    raise AssertionError(f"server died before the task ran:\n{output[-4000:]}")
                time.sleep(0.1)
            assert started_marker.exists(), "executor never picked the task up"
            snapshot = _get_task(port, task_id)
            assert snapshot["status"] == "coding", snapshot

            rc, elapsed, output = _sigterm_and_wait(proc)
        finally:
            if proc.poll() is None:
                proc.kill()

        assert rc is not None, (
            f"process still alive {_EXIT_DEADLINE_S:g}s after SIGTERM with an in-flight task"
        )
        assert _clean_signal_exit(rc), f"expected clean exit, got rc={rc}\n{output[-4000:]}"
        # The drain waited out its bounded timeout before cancelling — the
        # process must not exit before the drain window, nor hang past it.
        assert elapsed >= drain_timeout_s * 0.8, (
            f"exited after {elapsed:.1f}s — the bounded drain wait never happened"
        )
        assert elapsed < _EXIT_DEADLINE_S
        # Failure state: the runner announced the drain of the in-flight task,
        # then the cancellation it had to record when the bounded wait expired.
        # (These are the `stop()` markers — the `drain()` log names are the old
        # signal-handler path, removed with #819.)
        assert "draining_active_tasks" in output
        assert "tasks_cancelled_on_shutdown" in output, (
            f"no failure state recorded for the cancelled task:\n{output[-4000:]}"
        )
        assert "maistro_engine_stopped" in output


@pytest.mark.skipif(not _docker_ready(), reason=f"docker or {_SANDBOX_IMAGE} image unavailable")
class TestStopRestartLeavesNoOrphanedSandboxes:
    """AC-3 — graceful termination destroys MAIstro-owned sandbox containers."""

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_stop_destroys_seeded_sandbox_and_restart_is_clean(
        self, tmp_path: Path, workspace_root: Path
    ) -> None:
        port = _free_port()
        seed_marker = tmp_path / "seeded-container-id"
        # Provenance snapshot: the host may carry sandbox containers from other
        # processes (parallel lanes, crashed earlier runs). This test owns the
        # DELTA — containers appearing after this point that its own instance
        # did not destroy — not the host's global state.
        preexisting = set(_maistro_sandbox_containers())

        # The driver seeds the sandbox registry with a REAL Docker container
        # — exactly the object `cleanup_all_containers` owns at shutdown —
        # then serves the app. Nothing else in the process creates containers.
        proc = _spawn(
            f"""
            import asyncio, sys
            from pathlib import Path
            from tempfile import gettempdir

            from maistro.tools.sandbox import server as sandbox_server
            from maistro.tools.sandbox.docker import create_sandbox
            from maistro.tools.sandbox.workspace import ensure_workspace

            ws = ensure_workspace(
                str(Path(gettempdir()) / "maistro-workspace" / "sigterm-819" / "ac3" / "ws")
            )

            async def _seed():
                container = await create_sandbox(str(ws))
                sandbox_server._containers[str(ws)] = container
                Path({str(seed_marker)!r}).write_text(container.container_id)

            asyncio.run(_seed())

            import uvicorn
            from maistro_server.main import app
            config = uvicorn.Config(app, host="127.0.0.1", port={port}, log_level="info")
            asyncio.run(uvicorn.Server(config).serve())
            """,
            _server_env(),
        )
        try:
            _wait_ready(proc, port)
            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline and not seed_marker.exists():
                if proc.poll() is not None:
                    output = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
                    raise AssertionError(f"server died while seeding:\n{output[-4000:]}")
                time.sleep(0.2)
            assert seed_marker.exists(), "sandbox seed never completed"
            container_id = seed_marker.read_text().strip()
            assert container_id, "seeded container id is empty"
            assert _container_exists(container_id), (
                "seeded sandbox container should exist before shutdown"
            )

            rc, _, output = _sigterm_and_wait(proc)
        finally:
            if proc.poll() is None:
                proc.kill()

        # Stop half: clean exit, and the MAIstro-owned container is gone.
        assert rc is not None, f"process still alive {_EXIT_DEADLINE_S:g}s after SIGTERM"
        assert _clean_signal_exit(rc), f"expected clean exit, got rc={rc}\n{output[-4000:]}"
        remaining = set(_maistro_sandbox_containers())
        assert container_id not in remaining and not _container_exists(container_id), (
            f"sandbox container {container_id[:12]} was left orphaned after graceful "
            "termination — the shutdown cleanup callback did not destroy it"
        )
        assert remaining - preexisting == set(), (
            f"the stopped instance left orphaned sandbox containers: "
            f"{sorted(remaining - preexisting)}"
        )

        # Restart half: a fresh instance starts, sees no orphans, stops clean.
        restart_port = _free_port()
        restarted = _spawn(
            f"""
            import asyncio, uvicorn
            from maistro_server.main import app
            config = uvicorn.Config(app, host="127.0.0.1", port={restart_port}, log_level="info")
            asyncio.run(uvicorn.Server(config).serve())
            """,
            _server_env(),
        )
        try:
            _wait_ready(restarted, restart_port)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{restart_port}/health/startup", timeout=15
            ) as response:
                health = dict(json.loads(response.read()))
            assert health.get("startup_complete") is True, health
            after_restart = set(_maistro_sandbox_containers())
            assert after_restart - preexisting == set(), (
                f"the restarted instance inherited orphaned sandbox containers: "
                f"{sorted(after_restart - preexisting)}"
            )
            rc2, _, output2 = _sigterm_and_wait(restarted)
        finally:
            if restarted.poll() is None:
                restarted.kill()

        assert rc2 is not None, "restarted process still alive after SIGTERM"
        assert _clean_signal_exit(rc2), (
            f"restarted process did not exit cleanly: rc={rc2}\n{output2[-4000:]}"
        )
        # Its own stop also cleaned up after itself: nothing new remains.
        final = set(_maistro_sandbox_containers())
        assert final - preexisting == set(), (
            f"the restarted instance left orphaned sandbox containers: "
            f"{sorted(final - preexisting)}"
        )
