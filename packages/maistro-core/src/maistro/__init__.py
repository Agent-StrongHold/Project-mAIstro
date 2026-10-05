"""maistro-core: shared Python runtime for Maistro agent platforms."""

from __future__ import annotations

import importlib.metadata

# Single source of truth for version — read from installed package metadata.
try:
    __version__ = importlib.metadata.version("maistro-core")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"
