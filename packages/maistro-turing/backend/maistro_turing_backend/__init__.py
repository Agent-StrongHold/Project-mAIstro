"""Explicit application namespace for the Turing backend.

The reusable Turing runtime remains ``maistro_turing``; this package owns only
its HTTP application surface so it cannot collide with Hive's ``main`` or
``routes`` modules.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.9.0"
