"""Self-improving memory from tool call patterns.

The package's public importer is re-exported here: `learning_from_wisdom` is
the documented mapping from CoinSwarm's wisdom JSON onto the `Learning` record
(ADR-100126-5445), a published-library surface for downstream products. The
revisable learning lifecycle (`InMemoryLearningLifecycle`) is re-exported
beside it. Both are reachable exactly the way every other module of the
package is — through this package's `__init__`, which Python executes on the
first import of any sibling (`learnings.store`, `learnings.evidence`) the
container wires.
"""

from maistro.memory.learnings.gauntlet import ChainedGauntlet, OutcomeEvidenceGauntlet
from maistro.memory.learnings.lifecycle import InMemoryLearningLifecycle, effectiveness
from maistro.memory.learnings.wisdom import learning_from_wisdom

__all__ = [
    "ChainedGauntlet",
    "InMemoryLearningLifecycle",
    "OutcomeEvidenceGauntlet",
    "effectiveness",
    "learning_from_wisdom",
]
