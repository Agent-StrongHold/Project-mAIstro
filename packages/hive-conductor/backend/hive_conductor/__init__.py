"""Collision-free application namespace for the Hive Conductor backend.

The backend is an application package rather than a collection of modules
resolved from a backend directory on ``sys.path``.  Keep all intra-application
imports under ``hive_conductor`` so it can run beside the Turing backend.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.9.0"
