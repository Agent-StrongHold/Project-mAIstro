"""Self-improving memory from tool call patterns.

The package's public importer is re-exported here: `learning_from_wisdom` is
the documented mapping from CoinSwarm's wisdom JSON onto the `Learning` record
(ADR-100126-5445), a published-library surface for downstream products. It is
reachable exactly the way every other module of the package is — through this
package's `__init__`, which Python executes on the first import of any
sibling (`learnings.store`, `learnings.evidence`) the container wires.
"""

from maistro.memory.learnings.wisdom import learning_from_wisdom

__all__ = ["learning_from_wisdom"]
