"""SIGTERM shutdown convergence — the drain must finish, the teardown must end.

Evidence for #2249: the engine's SIGTERM path never converged during a drain
window. Two independent waits had no deadline:

1. **Uvicorn's connection drain.** `Server.shutdown` asks every open
   connection to shut down, then `_wait_tasks_to_complete` spins while any
   connection exists — and the `asyncio.wait_for` around it uses
   `timeout_graceful_shutdown`, which every engine launch path left `None`
   (`entrypoint.py` execed uvicorn without the flag; `Dockerfile.research`
   likewise). One wedged in-flight request or an open streaming response —
   exactly what a load generator's pooled clients produce across a kill/drain
   phase — spun that loop forever. Uvicorn runs `lifespan.shutdown()` only
   *after* the wait, so MAIstro's teardown (task drain, sandbox cleanup,
   client close, engine disposal) never ran at all. The process never exited;
   the compose grace period (`stop_grace_period: 30s`) ended in SIGKILL; the
   whole drain window filled with 5xx.

2. **The lifespan teardown itself.** Several phases inside `_runtime_lifespan`'s
   `finally` block owned no deadline: `cleanup_all_containers` loops over one
   bounded docker call per container with no bound on the whole, and the
   shared-client close, the container release and the engine disposal awaited
   their dependency for as long as it pleased. A docker daemon or database
   wedged by the same drain conditions held shutdown open past SIGKILL.

These tests pin the fix: the launch argv carries the bound, a wedged in-flight
request cannot hold SIGTERM open, and the bounded teardown phase helper
cancels a stuck step and proceeds. The subprocess test reproduces the reported
defect shape end to end (real signals, real server process, an in-flight
request that never completes) — the same shape `test_sigterm_shutdown.py`
uses for #819.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from maistro_server import entrypoint
from maistro_server import main as server_main

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Generous exit deadline. After SIGTERM the driver waits out the (shrunk)
#: connection grace, cancels the wedged request, then runs the lifespan
#: teardown — whose lazy `fastmcp` import alone can take tens of seconds on a
#: cold interpreter. The deadline proves the process *does* exit; it is not a
#: grace-period extension of the defect.
_EXIT_DEADLINE_S = 90.0


def _server_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env for a server subprocess: in-memory spine, auth off, info logs.

    Same shape as `test_sigterm_shutdown._server_env`: DEBUG=true so structlog
    keeps the info events the assertions read as teardown evidence.
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
            "ROUTER_API_KEY": "drain-test-router-key",
            # Startup validates API_KEY identities even when auth is disabled.
            "API_KEYS": '["drain-test:drain-test-api-key"]',
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


def _wait_ready(proc: subprocess.Popen[str], port: int, timeout_s: float = 60.0) -> None:
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


def _open_wedged_request(port: int) -> socket.socket:
    """Put one request in flight that the handler will never answer.

    Returns the raw socket, deliberately left open: an unanswered in-flight
    request is the drain-window shape the defect names. The handler awaits an
    event nobody ever sets, so only the graceful-shutdown deadline can end it.
    """
    conn = socket.create_connection(("127.0.0.1", port), timeout=5)
    conn.sendall(b"GET /drain-2249-wedged HTTP/1.1\r\nHost: localhost\r\n\r\n")
    return conn


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


@pytest.fixture()
def wedge_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Server env with the connection grace shrunk to an observable 2s.

    The override flows through `_connection_grace_s` — the same seam the
    entrypoint reads — so the subprocess exercises the real binding, just
    with a deadline a test can afford to wait out.
    """
    env = _server_env({"MAISTRO_SHUTDOWN_CONNECTION_GRACE": "2"})
    yield env


class TestLaunchArgvCarriesTheBound:
    """The connection drain is bounded where the defect lived: the argv."""

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_uvicorn_args_include_the_graceful_shutdown_deadline(self) -> None:
        args = entrypoint._uvicorn_args()
        flag_index = args.index("--timeout-graceful-shutdown")
        # The default sits strictly below the shipped compose grace
        # (stop_grace_period: 30s), leaving the teardown room to run.
        assert float(args[flag_index + 1]) == entrypoint.DEFAULT_CONNECTION_GRACE_S
        # Uvicorn's CLI requires an integer here: "10.0" would abort the exec
        # with "is not a valid integer".
        assert str(int(args[flag_index + 1])) == args[flag_index + 1]
        assert entrypoint.DEFAULT_CONNECTION_GRACE_S < 30.0
        # The rest of the argv is the exec this entrypoint always ran.
        assert args[args.index("-m") + 1] == "uvicorn"
        assert args[args.index("-m") + 2] == "maistro_server.main:app"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param("", entrypoint.DEFAULT_CONNECTION_GRACE_S, id="unset-defaults"),
            pytest.param("3", 3.0, id="override-honored"),
            pytest.param("  4.5  ", 4.5, id="whitespace-tolerated"),
            pytest.param(
                "nonsense", entrypoint.DEFAULT_CONNECTION_GRACE_S, id="garbage-falls-back"
            ),
            pytest.param("-5", 0.0, id="negative-clamped-not-poisoned"),
        ],
    )
    def test_connection_grace_parsing(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: float
    ) -> None:
        monkeypatch.setenv("MAISTRO_SHUTDOWN_CONNECTION_GRACE", raw)
        assert entrypoint._connection_grace_s() == expected


class TestTeardownPhaseBound:
    """One wedged phase must not hold the whole shutdown open (#2249)."""

    @pytest.fixture(autouse=True)
    def _short_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server_main, "TEARDOWN_PHASE_TIMEOUT", 0.25)

    @staticmethod
    def _stub_logger(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
        events: dict[str, list[dict[str, Any]]] = {}

        async def awarning(event: str, **kwargs: Any) -> None:
            events.setdefault(event, []).append(kwargs)

        async def aerror(event: str, **kwargs: Any) -> None:
            events.setdefault(event, []).append(kwargs)

        monkeypatch.setattr(
            server_main,
            "logger",
            type(
                "_StubLogger",
                (),
                {
                    "awarning": staticmethod(awarning),
                    "aerror": staticmethod(aerror),
                },
            )(),
        )
        return events

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_a_hung_phase_is_cancelled_and_shutdown_proceeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events = self._stub_logger(monkeypatch)
        started = asyncio.Event()

        async def wedged_cleanup() -> None:
            started.set()
            await asyncio.Event().wait()  # docker daemon never answers again

        step = asyncio.create_task(server_main._teardown_phase("sandbox_cleanup", wedged_cleanup))
        await asyncio.wait_for(started.wait(), timeout=5.0)
        # The helper returns at the deadline — it does not hang with the step.
        await asyncio.wait_for(step, timeout=10.0)
        timed_out = events["lifespan_teardown_phase_timeout"]
        assert timed_out[0]["phase"] == "sandbox_cleanup"
        assert timed_out[0]["timeout_s"] == 0.25

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_a_failing_phase_is_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events = self._stub_logger(monkeypatch)

        async def exploded() -> None:
            raise RuntimeError("pool already released")

        # No exception escapes: shutdown must proceed past a failed phase.
        await server_main._teardown_phase("engine_dispose", exploded)
        failures = events["lifespan_teardown_phase_failed"]
        assert failures[0]["phase"] == "engine_dispose"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_a_healthy_phase_runs_to_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events = self._stub_logger(monkeypatch)
        completed = asyncio.Event()

        async def settles_normally() -> None:
            completed.set()

        await server_main._teardown_phase("shared_clients_close", settles_normally)
        assert completed.is_set()
        assert events == {}


# Imports placed after the module docstring section above so the synchronous
# helpers read first; asyncio is needed by the phase-bound tests.


class TestSigtermConvergesWithWedgedInflightRequest:
    """The reported defect, end to end: drain window, wedged request, SIGTERM."""

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_sigterm_exits_bounded_and_runs_the_lifespan_teardown(
        self, wedge_env: dict[str, str]
    ) -> None:
        grace_s = float(wedge_env["MAISTRO_SHUTDOWN_CONNECTION_GRACE"])
        port = _free_port()

        # The exact launch shape the entrypoint execs, with the bound the
        # argv carries: uvicorn parses `--timeout-graceful-shutdown <n>` into
        # `Config(timeout_graceful_shutdown=<n>)`, so building the Config
        # with `_connection_grace_s()` exercises the same binding the
        # container runs.
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    f"""
                    import asyncio, uvicorn
                    from maistro_server.main import app
                    from maistro_server.entrypoint import _connection_grace_s

                    @app.get("/drain-2249-wedged")
                    async def wedged():
                        await asyncio.Event().wait()  # upstream wedged mid-drain

                    config = uvicorn.Config(
                        app,
                        host="127.0.0.1",
                        port={port},
                        log_level="info",
                        timeout_graceful_shutdown=_connection_grace_s(),
                    )
                    asyncio.run(uvicorn.Server(config).serve())
                    """
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=wedge_env,
            text=True,
        )
        wedged: socket.socket | None = None
        try:
            _wait_ready(proc, port)
            wedged = _open_wedged_request(port)

            rc, elapsed, output = _sigterm_and_wait(proc)
        finally:
            if wedged is not None:
                wedged.close()
            if proc.poll() is None:
                proc.kill()

        assert rc is not None, (
            f"process still alive {_EXIT_DEADLINE_S:g}s after SIGTERM with a wedged "
            "in-flight request — the #2249 defect: nothing bounded the drain"
        )
        # Uvicorn restores the default handler and dies of SIGTERM by design
        # after a graceful stop (see test_sigterm_shutdown._clean_signal_exit).
        assert rc in (0, -signal.SIGTERM), f"expected clean exit, got rc={rc}\n{output[-4000:]}"
        # The bound actually waited before cancelling: the process must not
        # exit before the grace window, nor hang past it.
        assert elapsed >= grace_s * 0.8, (
            f"exited after {elapsed:.1f}s — the connection grace never applied"
        )
        assert elapsed < _EXIT_DEADLINE_S
        # The deadline fired against the wedged request ...
        assert "timeout graceful shutdown exceeded" in output, (
            f"the graceful-shutdown deadline never cancelled the wedged request:\n{output[-4000:]}"
        )
        # ... and what follows it — the lifespan teardown MAIstro owns — ran
        # to its final callback, which is what never happened before the fix.
        assert "Application shutdown complete" in output
        assert "maistro_engine_stopped" in output, (
            f"lifespan teardown did not reach its final callback:\n{output[-4000:]}"
        )
