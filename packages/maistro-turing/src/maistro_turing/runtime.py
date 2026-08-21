"""DEAD CODE — superseded by the `maistro_turing.runtime` package (runtime/__init__.py).

BUG (found in Phase 23 coverage work): a same-named `runtime/` package directory
(empty placeholder scaffolding present since the original monorepo consolidation
commit) shadows this flat module on import — Python always resolves
`import maistro_turing.runtime` to the package, never to this file. That made
`TuringConfig`, `load_turing_config`, `TuringActor`, and `TuringChatSession`
permanently unreachable through their documented import path and untestable.

Fix applied: the implementation was copied into `runtime/__init__.py` (the path
that actually wins), which is now the real, imported, and tested module. This
file is inert — Python never loads it as `maistro_turing.runtime` while the
sibling package directory exists. Left in place only because this package is
shared with another concurrent work stream and the file could not be deleted
in this change; do not add new code here, it will never run.
"""

from __future__ import annotations
