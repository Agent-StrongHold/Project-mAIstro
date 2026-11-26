"""RSI service -- exposes maistro-rsi's self-improvement loops to hive-conductor.

Two operator-facing modes (per the RSI production-readiness design):

* **cleanup / improvement** (entry point A): drives the self-improvement loop
  against a repo + test command. Since #509 this is *dispatched*: the whole
  loop (agent, git, tests, coverage, fitness) runs inside an ephemeral runner
  container (`services.rsi_container_dispatch`), because an in-process loop
  executes candidate-authored code as this process (#305) — this service only
  builds the launch argv, polls the mounted report directory, and relays the
  container's exit code.
* **greenfield exploration** (entry point B): drives ``RsiCycle`` — compete genomes
  against benchmarks (SWE-Bench Pro) in an Elo tournament, no repo test gate.

Runs are on-demand (an operator starts one with a target + config), long-lived, and
tracked here so the UI can poll status / cycles / promotions / exported patches.
maistro-rsi is an optional dependency: if it isn't importable in this process the
service reports ``available=False`` (the greenfield path degrades; cleanup runs
are gated on the container backend instead) so the rest of the app is
unaffected (mirrors how ``services.evolution`` degrades).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from services import rsi_container_dispatch as _dispatch

logger = logging.getLogger(__name__)

_service: _RsiService | None = None

RunMode = Literal["cleanup", "greenfield"]
RunStatus = Literal["pending", "running", "completed", "errored", "stopped"]


def get_rsi_service() -> _RsiService:
    global _service
    if _service is None:
        _service = _RsiService()
    return _service


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rsi_available() -> bool:
    try:
        import maistro_rsi  # noqa: F401
    except Exception:
        return False
    return True


@dataclass
class RunState:
    run_id: str
    mode: RunMode
    config: dict[str, Any]
    status: RunStatus = "pending"
    started_at: str = field(default_factory=_now)
    ended_at: str | None = None
    cycles: int = 0
    promotions: int = 0
    last_error: str | None = None
    summary: str | None = None
    report_dir: str | None = None
    export_dir: str | None = None
    #: Set once the run is dispatched (#509): the cleanup loop lives in an
    #: ephemeral container, and cancellation must stop THAT, not just an
    #: asyncio task. Surfaced in the API so an operator can find the same
    #: container Docker sees (`docker ps --filter label=maistro.rsi.run-id`).
    container_id: str | None = None
    task: asyncio.Task[Any] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "cycles": self.cycles,
            "promotions": self.promotions,
            "last_error": self.last_error,
            "summary": self.summary,
            "config": self.config,
            "report_dir": self.report_dir,
            "export_dir": self.export_dir,
            "container_id": self.container_id,
        }


class _RsiService:
    #: How often a dispatched run's report directory is polled for progress.
    #: A class attribute because tests shrink it; production polls on the
    #: order of seconds, not the checkpoint cadence of the loop itself.
    poll_interval_s: float = 5.0

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    @property
    def available(self) -> bool:
        return _rsi_available()

    def list_runs(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._runs.values()]

    def get_run(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def stop_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or run.task is None or run.task.done():
            return False
        # Stopping a dispatched run means stopping its container (#509) — a
        # bounded `docker stop`, a different operation from cancelling the
        # asyncio task with a different failure mode. Both happen: the
        # container so the loop actually dies, the task so the service record
        # settles without waiting for it.
        if run.container_id:
            try:
                stopped = _dispatch.stop_container(run.container_id)
            except Exception:
                logger.warning(
                    "rsi run %s: stopping container %s failed",
                    run_id,
                    run.container_id,
                    exc_info=True,
                )
            else:
                if not stopped:
                    logger.info(
                        "rsi run %s: container %s was already gone", run_id, run.container_id
                    )
        run.task.cancel()
        run.status = "stopped"
        run.ended_at = _now()
        return True

    def start_run(self, mode: RunMode, config: dict[str, Any]) -> RunState:
        run_id = uuid.uuid4().hex[:12]
        run = RunState(run_id=run_id, mode=mode, config=config)
        self._runs[run_id] = run
        run.task = asyncio.ensure_future(self._drive(run))
        run.status = "running"
        return run

    async def _drive(self, run: RunState) -> None:
        try:
            if run.mode == "cleanup":
                await self._drive_cleanup(run)
            else:
                await self._drive_greenfield(run)
            if run.status not in ("stopped", "errored"):
                run.status = "completed"
        except asyncio.CancelledError:
            run.status = "stopped"
            raise
        except _dispatch.DispatchError as exc:
            run.status = "errored"
            # Dispatch errors are composed server-side from exit codes and
            # truncated docker stderr — no provider replies, no candidate
            # output — so the operator-facing record can carry the reason.
            run.last_error = str(exc)
            logger.warning("rsi run %s failed: %s", run.run_id, exc, exc_info=True)
        except Exception as exc:
            run.status = "errored"
            # The run record is returned to the browser; the exception text
            # (paths, hosts, provider replies) stays in the server log.
            run.last_error = f"{type(exc).__name__}: run failed; see server logs"
            logger.warning("rsi run %s failed: %s", run.run_id, exc, exc_info=True)
        finally:
            run.ended_at = _now()

    # ── cleanup / improvement (contained dispatch, #509) ────────────────────────────────
    async def _drive_cleanup(self, run: RunState) -> None:
        """Run the cleanup loop inside an ephemeral container — never here.

        #305 closed this route because the in-process loop executes
        candidate-authored code as the Conductor process. #509 re-opens it
        with the loop dispatched the way `tools/run_rsi_isolated.sh` runs it:
        agent, git, tests, coverage and the fitness gate all execute in the
        runner container, and this process only builds the launch argv, polls
        the mounted report directory, and relays the container's exit code.
        """
        cfg = run.config
        # `test_argv` and `isolation` are resolved by routes/rsi.py against
        # services.rsi_execution_policy before they reach here, and both are
        # required (#305). Defaulting either would give an in-process caller a
        # quieter version of the door the route just closed: an absent argv
        # falls back to a shell command, an absent isolation falls back to the
        # host. Refuse instead.
        test_argv = tuple(cfg.get("test_argv") or ())
        if not test_argv:
            raise ValueError("an RSI run requires a policy-resolved test_argv")
        isolation = cfg.get("isolation") or ""
        if isolation != "container":
            raise ValueError(
                f"an RSI run requires container isolation, not {isolation!r} — "
                "candidate code does not execute on the host"
            )

        spec = _dispatch.build_spec(
            run_id=run.run_id,
            repo=Path(cfg["repo_path"]),
            test_argv=test_argv,
            cycles=int(cfg.get("cycles", 3)),
            agent_turns=int(cfg.get("agent_turns", 6)),
            model=cfg.get("model"),
            objective=cfg.get("objective") or "",
            targets=list(cfg.get("targets", []) or []),
            use_fitness=bool(cfg.get("fitness", False)),
            coverage_source=cfg.get("coverage_source") or ".",
            coverage_pytest_args=cfg.get("coverage_pytest_args") or "",
            scout=bool(cfg.get("scout", False)),
            genome_models=[
                m.strip() for m in (cfg.get("genome_models") or "").split(",") if m.strip()
            ],
            roster_size=int(cfg.get("roster_size", 4) or 4),
        )
        # Derived from the run id under the server's working root (#305), and
        # the same directory the container writes reports into — the channel
        # through which all progress crosses back to the host.
        run.report_dir = str(spec.report_dir)
        run.export_dir = str(spec.report_dir / "export")

        # The launch runs in a thread the event loop can only abandon, not
        # interrupt, so a stop that races this window would see no
        # container_id and leave whatever `docker run` starts unowned. Keep the
        # future alive through cancellation (shield) so the cleanup below can
        # wait out the bounded launch and stop the container it produced.
        launch_task: asyncio.Task[str] | None = None
        container_id: str | None = None
        try:
            launch_task = asyncio.ensure_future(asyncio.to_thread(_dispatch.launch, spec))
            container_id = await asyncio.shield(launch_task)
            run.container_id = container_id
            logger.info(
                "rsi run %s dispatched into container %s (%s)",
                run.run_id,
                container_id,
                _dispatch.describe(spec),
            )
            exit_code = await self._await_container(run, spec.report_dir, container_id)
        except asyncio.CancelledError:
            # The task was cancelled without stop_run having a container to
            # stop: stop here too, so no dispatched run outlives its service
            # record by accident. stop_run stops the container and marks the
            # record before cancelling, so its path (cancel during the wait,
            # container_id already set) skips the stop below — one bounded
            # stop, not a second one racing the first. Best-effort — a failure
            # to stop must not mask the cancellation itself.
            stop_id = container_id if run.status != "stopped" else None
            if container_id is None and launch_task is not None:
                # Cancelled mid-launch: the worker thread outlives the cancel
                # and may still start the container, and stop_run saw no
                # container_id — nothing else will stop it. Wait out the
                # bounded launch and stop what it actually started.
                try:
                    container_id = await asyncio.shield(launch_task)
                except Exception:
                    container_id = None
                if container_id:
                    run.container_id = container_id
                    stop_id = container_id
            if stop_id:
                try:
                    await asyncio.to_thread(_dispatch.stop_container, stop_id)
                except Exception:
                    logger.warning(
                        "rsi run %s: container %s survived cancellation",
                        run.run_id,
                        stop_id,
                        exc_info=True,
                    )
            raise
        if exit_code != 0:
            raise _dispatch.DispatchError(
                f"the runner container exited with code {exit_code} — "
                f"see its logs: docker logs rsi-run-{run.run_id}"
            )
        counts = await asyncio.to_thread(_dispatch.poll_reports, spec.report_dir)
        run.cycles = counts.get("cycles_run", run.cycles)
        run.promotions = counts.get("promotions", run.promotions)
        run.summary = await asyncio.to_thread(_dispatch.final_summary, spec.report_dir)

    async def _await_container(self, run: RunState, report_dir: Path, container_id: str) -> int:
        """Wait out the container, polling the mounted reports for progress.

        `docker wait` is a blocking call, so it runs in a thread; the polling
        keeps `cycles`/`promotions` live for the UI while the loop works. If
        the backend loses the container — daemon restart, `--rm` race — the
        wait raises and the run is reported errored rather than left running
        forever against a container that no longer exists.
        """
        wait_task = asyncio.ensure_future(asyncio.to_thread(_dispatch.wait, container_id))
        try:
            while not wait_task.done():
                counts = await asyncio.to_thread(_dispatch.poll_reports, report_dir)
                if counts:
                    run.cycles = counts.get("cycles_run", run.cycles)
                    run.promotions = counts.get("promotions", run.promotions)
                await asyncio.sleep(self.poll_interval_s)
            return await wait_task
        except BaseException:
            wait_task.cancel()
            raise

    # ── greenfield exploration (RsiCycle / benchmark tournament) ────────────
    async def _drive_greenfield(self, run: RunState) -> None:
        # RsiCycle is the benchmark-tournament path (SWE-Bench Pro). It is wired
        # separately from LocalRsiLoop and is scaffolded here — full integration
        # (benchmark selection, quarantine, Elo battle reporting) lands with the
        # greenfield UI surface. Until then, surface a clear not-implemented state.
        run.status = "errored"
        run.last_error = (
            "greenfield mode (RsiCycle benchmark tournament) is not wired yet — "
            "use cleanup mode, or see maistro_rsi.cli / runner.RsiCycle."
        )


def status() -> dict[str, Any]:
    svc = get_rsi_service()
    return {
        "available": svc.available,
        "active_runs": sum(1 for r in svc._runs.values() if r.status == "running"),
        "total_runs": len(svc._runs),
    }
