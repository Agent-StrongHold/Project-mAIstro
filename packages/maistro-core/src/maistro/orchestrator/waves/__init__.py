"""Parallel agent waves (ADR-052) + Repertoire wave ensemble (ADR-071).

Submodules:
  - ``fan_out`` / ``fan_in`` / ``types``: git-based wave fan-out/fan-in (SPEC-255).
  - ``ensemble``: SuperPlanner waves as a Repertoire ensemble (SPEC-070226-b624).

#2314 absorbs the SPEC-255 helpers onto the Graph/Run fan-out path: they are
exported here so process imports of ``maistro.orchestrator.waves`` (via the
ensemble SuperPlanner surface) reach them, and ``validate_fan_out_width`` is
the shared ceiling ``agent.synth_dag`` / exploration waves consult.
"""

from maistro.orchestrator.waves.ensemble import (
    CheckpointStore,
    InMemoryCheckpointStore,
    LLMJudgeComparator,
    MultiStrategyExpander,
    QualityComparator,
    ResultComparator,
    SuperPlannerConfig,
    Wave,
    WaveEnsembleError,
    WaveEnsembleOutput,
    WaveEnsembleStrategy,
    WaveExpander,
    WaveOrchestrator,
    WaveResult,
    WaveTask,
)
from maistro.orchestrator.waves.fan_in import fan_in
from maistro.orchestrator.waves.fan_out import MAX_PARALLEL_CEILING, validate_fan_out_width
from maistro.orchestrator.waves.types import (
    ConflictRecord,
    FanInResult,
    WaveHandle,
    WaveSpec,
)

__all__ = [
    "MAX_PARALLEL_CEILING",
    "CheckpointStore",
    "ConflictRecord",
    "FanInResult",
    "InMemoryCheckpointStore",
    "LLMJudgeComparator",
    "MultiStrategyExpander",
    "QualityComparator",
    "ResultComparator",
    "SuperPlannerConfig",
    "Wave",
    "WaveEnsembleError",
    "WaveEnsembleOutput",
    "WaveEnsembleStrategy",
    "WaveExpander",
    "WaveHandle",
    "WaveOrchestrator",
    "WaveResult",
    "WaveSpec",
    "WaveTask",
    "fan_in",
    "validate_fan_out_width",
]
