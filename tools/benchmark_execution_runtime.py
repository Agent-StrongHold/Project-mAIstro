#!/usr/bin/env python3
"""Load-test the Python execution runtime migration-trigger metrics.

Example:
    uv run --package maistro-core python tools/benchmark_execution_runtime.py \
        --runs 1000 --concurrency 64 --task-delay-ms 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from typing import Any

from maistro.runtime import PythonExecutionRuntime


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--task-delay-ms", type=float, default=5.0)
    parser.add_argument("--lag-samples", type=int, default=100)
    return parser.parse_args()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
    return ordered[index]


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.runs < 1:
        raise ValueError("--runs must be >= 1")
    if args.concurrency < 1:
        raise ValueError("--concurrency must be >= 1")
    if args.task_delay_ms < 0:
        raise ValueError("--task-delay-ms must be >= 0")
    if args.lag_samples < 1:
        raise ValueError("--lag-samples must be >= 1")

    runtime = PythonExecutionRuntime(max_concurrency=args.concurrency)
    delay_s = args.task_delay_ms / 1000.0
    lag_samples: list[float] = []
    stop_sampling = asyncio.Event()

    async def executor(_graph: Any, _context: Any) -> None:
        await asyncio.sleep(delay_s)

    async def sample_lag() -> None:
        while not stop_sampling.is_set() and len(lag_samples) < args.lag_samples:
            lag_samples.append(await runtime.sample_event_loop_lag(0.01))

    before = runtime.metrics()
    started = time.perf_counter()
    sampler = asyncio.create_task(sample_lag())
    await asyncio.gather(
        *[
            runtime.execute(
                None,
                None,
                execution_id=f"bench-{index}",
                executor=executor,
            )
            for index in range(args.runs)
        ]
    )
    wall_s = time.perf_counter() - started
    stop_sampling.set()
    await sampler
    after = runtime.metrics()

    average_wait = after.scheduling_wait_seconds_total / after.executions_started
    return {
        "runs": args.runs,
        "configured_concurrency": args.concurrency,
        "task_delay_ms": args.task_delay_ms,
        "wall_seconds": wall_s,
        "throughput_runs_per_second": args.runs / wall_s,
        "runtime_cpu_seconds_delta": after.process_cpu_seconds - before.process_cpu_seconds,
        "max_rss_bytes": after.max_rss_bytes,
        "peak_concurrency": after.peak_concurrency,
        "scheduling_wait_seconds_total": after.scheduling_wait_seconds_total,
        "scheduling_wait_ms_average": average_wait * 1000.0,
        "event_loop_lag_ms_average": (statistics.fmean(lag_samples) if lag_samples else 0.0),
        "event_loop_lag_ms_p99": _percentile(lag_samples, 0.99),
        "event_loop_lag_ms_max": max(lag_samples, default=0.0),
        "executions_completed": after.executions_completed,
        "executions_failed": after.executions_failed,
        "executions_yielded": after.executions_yielded,
        "executions_cancelled": after.executions_cancelled,
        "executions_timed_out": after.executions_timed_out,
    }


def main() -> None:
    print(json.dumps(asyncio.run(_run(_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
