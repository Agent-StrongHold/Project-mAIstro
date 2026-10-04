"""Self-improving memory from tool call patterns.

Re-exports the independent-validation surface (#118): the Gauntlet protocol
and its outcome-evidence implementation are the library API a downstream
product configures between a learning's promotion threshold and the collective
repertoire (ADR-100126-9a4b). The promoter accepts any ``LearningGauntlet``;
no in-tree process entry point constructs the concrete classes, so this
package-level re-export is the module's one reachable import path.
"""

from maistro.memory.learnings.gauntlet import (
    ChainedGauntlet,
    GauntletEvidence,
    GauntletVerdict,
    LearningGauntlet,
    OutcomeEvidenceGauntlet,
    evidence_of,
)

__all__ = [
    "ChainedGauntlet",
    "GauntletEvidence",
    "GauntletVerdict",
    "LearningGauntlet",
    "OutcomeEvidenceGauntlet",
    "evidence_of",
]
