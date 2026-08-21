"""Fan-out width validation against the substrate-enforced cap (SPEC-255 / ADR-052)."""

from __future__ import annotations

from maistro.orchestrator.waves.types import WaveSpec

MAX_PARALLEL_CEILING = 16


def validate_fan_out_width(wave_specs: tuple[WaveSpec, ...], *, max_parallel: int) -> None:
    if max_parallel > MAX_PARALLEL_CEILING:
        raise ValueError(
            f"max_parallel={max_parallel} exceeds MAX_PARALLEL_CEILING={MAX_PARALLEL_CEILING}"
        )
    if len(wave_specs) > max_parallel:
        raise ValueError(
            f"wave_specs has {len(wave_specs)} entries, exceeding max_parallel={max_parallel}"
        )
