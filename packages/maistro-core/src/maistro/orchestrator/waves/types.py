"""Parallel agent wave types (SPEC-255 / ADR-052)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class WaveSpec:
    wave_id: str
    agent_recipe: str
    inputs: dict[str, Any]


@dataclass(frozen=True)
class WaveHandle:
    wave_id: str
    branch: str
    status: Literal["running", "succeeded", "failed"]
    head_sha: str | None


@dataclass(frozen=True)
class ConflictRecord:
    path: str
    wave_a: str
    wave_b: str
    sha_a: str
    sha_b: str


@dataclass(frozen=True)
class FanInResult:
    merged_sha: str | None
    conflicts: tuple[ConflictRecord, ...]
    failed_waves: tuple[WaveHandle, ...]
