"""maistro-core: shared Python runtime for Maistro agent platforms."""

from __future__ import annotations

import importlib.metadata

# The public extension contract (#950) is part of the package's front door:
# external developers import it as `from maistro import extensions`, and the
# reachability ratchet treats the SDK surface as wired through this root.
from maistro import extensions

# Single source of truth for version — read from installed package metadata.
try:
    __version__ = importlib.metadata.version("maistro-core")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"

__all__ = ["__version__", "extensions"]
