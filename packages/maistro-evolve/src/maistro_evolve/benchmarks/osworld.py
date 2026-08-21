from __future__ import annotations

from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import OSWORLD_SAMPLES

__all__ = ["run_osworld"]


async def run_osworld(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """OSWorld is not implemented and is not registered in ``PROXY_BENCHMARKS``.

    There is no honest way to score this at any fidelity: OSWorld's real
    methodology drives an actual desktop OS (open Settings, connect to WiFi,
    change the wallpaper) and verifies the resulting UI/filesystem state. This
    repo has no VM, no display server, no GUI automation library, and no
    accessibility/screenshot channel to drive or verify that — genuinely
    greenfield, not a smaller version of an existing capability. The previous
    implementation scored a model's *description* of what it would click
    against a list of expected action-name strings, which is not a lite
    version of OSWorld's methodology, just a heuristic wearing its name.

    Raises rather than returning any score, fabricated or otherwise (SPEC-202
    §3: real desktop-VM adapter is future work; ``OSWORLD_SAMPLES`` stays in
    ``datasets.py`` as reference material for that).
    """
    raise NotImplementedError(
        "osworld requires real desktop-VM execution infrastructure (display "
        "server, GUI automation, state verification) that does not exist in "
        "this repo yet (SPEC-202 §3, phase 4). It is intentionally not "
        f"registered in PROXY_BENCHMARKS. {len(OSWORLD_SAMPLES)} reference "
        "task definitions remain in datasets.py for when that lands."
    )
