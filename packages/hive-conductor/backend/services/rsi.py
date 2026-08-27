"""RSI service -- exposes maistro-rsi's self-improvement loops to hive-conductor.

Two operator-facing modes (per the RSI production-readiness design):

* **cleanup / improvement** (entry point A): drives ``LocalRsiLoop`` — clone a repo,
  ratchet gate-passing improvements against the repo's own test command. This is the
  proven, operator-run path.
* **greenfield exploration** (entry point B): drives ``RsiCycle`` — compete genomes
  against benchmarks (SWE-Bench Pro) in an Elo tournament, no repo test gate.

Runs are on-demand (an operator starts one with a target + config), long-lived, and
tracked here so the UI can poll status / cycles / promotions / exported patches.
maistro-rsi is an optional dependency: if it isn't importable in this process the
service reports ``available=False`` and the routes 503, so the rest of the app is
unaffected (mirrors how ``services.evolution`` degrades).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

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
        }


class _RsiService:
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
        except Exception as exc:
            run.status = "errored"
            run.last_error = str(exc)
            logger.warning("rsi run %s failed: %s", run.run_id, exc, exc_info=True)
        finally:
            run.ended_at = _now()

    # ── cleanup / improvement (LocalRsiLoop) ────────────────────────────────
    async def _drive_cleanup(self, run: RunState) -> None:
        import tempfile
        from pathlib import Path

        from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop, make_builders_apply_patch

        cfg = run.config
        # The UI omits work_root/report_dir; LocalRsiLoop requires the first
        # (Path(None) → TypeError before a single cycle) and silently skips
        # checkpoints + promotion review records without the second — which
        # left the patch-review page permanently empty. Allocate both the way
        # the CLI path does.
        work_root = cfg.get("work_root") or tempfile.mkdtemp(prefix=f"rsi-{run.run_id}-")
        report_dir = cfg.get("report_dir") or str(Path(work_root) / "reports")
        genome_models = [
            m.strip() for m in (cfg.get("genome_models") or "").split(",") if m.strip()
        ]
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
        lc = LocalRsiConfig(
            repo_path=cfg["repo_path"],
            # Kept only so logs and reports can name what ran; nothing executes
            # it. `test_argv` is what the loop runs, without a shell.
            test_command=" ".join(test_argv),
            test_argv=test_argv,
            isolation=isolation,
            work_root=work_root,
            max_cycles=int(cfg.get("cycles", 3)),
            model=cfg.get("model"),
            agent_turns_per_cycle=int(cfg.get("agent_turns", 6)),
            objective=cfg.get("objective") or "",
            targets=list(cfg.get("targets", []) or []),
            use_fitness=bool(cfg.get("fitness", False)),
            coverage_source=cfg.get("coverage_source") or ".",
            coverage_pytest_args=cfg.get("coverage_pytest_args") or "",
            report_dir=report_dir,
            export_patches=cfg.get("export_dir"),
            # Tournament settings: the UI shows working roster/scout controls,
            # so not forwarding them meant every run silently executed with
            # different settings than the operator chose.
            genome_db=str(Path(work_root) / "population.db") if genome_models else None,
            genome_models=genome_models,
            roster_size=int(cfg.get("roster_size", 4) or 4),
            scout=bool(cfg.get("scout", False)),
        )
        run.report_dir = lc.report_dir
        run.export_dir = lc.export_patches
        apply_fn = make_builders_apply_patch(
            objective=lc.objective or "",
            model=lc.model,
            max_agent_turns=lc.agent_turns_per_cycle,
        )
        loop = LocalRsiLoop(lc, apply_patch=apply_fn)
        # run() is synchronous: driven inline it would block the event loop for
        # the whole multi-cycle run (status/stop unservable) and `await` on its
        # dataclass result raised TypeError, marking every finished run errored.
        result = await asyncio.to_thread(loop.run)
        run.cycles = getattr(result, "cycles_run", 0) or len(getattr(result, "cycles", []) or [])
        run.promotions = getattr(result, "promotions", 0)
        run.summary = result.summary() if hasattr(result, "summary") else None

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
