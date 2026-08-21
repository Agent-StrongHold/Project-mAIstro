"""Turing Cage — deterministic enforcement layer.

This package is mounted READ-ONLY in Turing's container.
No code in this package may be modified by Turing or any automated process.
CI gate auto-rejects PRs touching cage/ or eval/.
"""

from cage.immutable_paths import IMMUTABLE_PATHS, is_immutable
from cage.memory_rules import MemoryRules
from cage.permission_boundary import PermissionBoundary
from cage.turing_cage import TuringCage

__all__ = ["IMMUTABLE_PATHS", "MemoryRules", "PermissionBoundary", "TuringCage", "is_immutable"]
