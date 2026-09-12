"""Builds the ``PermissionTable`` consumed by ``Sentinel.pre_call`` / ``authorize``.

Table-miss semantics are FAIL-CLOSED (ADR-072726-0d6b, implemented for #1165,
as amended formal invariant I6): an absent entry denies, so a deployment that
configures nothing denies every permission-table lookup instead of authorizing
every tool. This module therefore only *adds* explicit decisions; it never
reopens the default -- the only permissive path is Sentinel's explicit
``allow_on_miss=True`` compatibility mode, which no production wiring passes.

At the shipped defaults (``preset="none"``, ``permissions={}``) the table is
empty, so every Sentinel authorization now denies until an operator configures
explicit permissions (or a preset). That is the #1165 invariant: an empty
production permission table cannot authorize every tool.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from maistro.security._types import PermissionTable
from maistro.security.patterns import DANGEROUS_TOOL_NAMES

# "none" is handled by absence (an empty table), not by an explicit entry
# here -- see build_permission_table's default.
PERMISSION_PRESETS: dict[str, frozenset[str]] = {
    "dangerous_tools_admin": DANGEROUS_TOOL_NAMES,
}

#: Every accepted value of ``preset``. Membership is checked against this rather
#: than comparing ``preset != "none"``: the mutation gate showed that comparison
#: surviving as ``preset is not "none"``, which passes only because CPython
#: interns the literal -- a caller building the string dynamically would have
#: taken the other branch. A set membership test has no such identity trap.
VALID_PRESETS: frozenset[str] = frozenset({"none", *PERMISSION_PRESETS})

#: Immutable empty default. Not ``| None``: cosmic-ray mutates the ``|`` in a
#: union annotation into every other binary operator, and because
#: ``from __future__ import annotations`` means annotations are never evaluated,
#: none of those mutants is killable by any test -- 11 unkillable survivors that
#: dragged this file's kill rate to 63.9%. A single immutable sentinel says the
#: same thing with no annotation-level operator to mutate.
_NO_PERMISSIONS: Mapping[str, Sequence[str]] = MappingProxyType({})


def build_permission_table(
    *,
    preset: str = "none",
    permissions: Mapping[str, Sequence[str]] = _NO_PERMISSIONS,
) -> PermissionTable:
    """Build a ``PermissionTable`` from an optional preset plus explicit overrides.

    - ``preset="none"`` (the default) yields an empty table. Under the
      fail-closed default (ADR-072726-0d6b, #1165) an empty table denies
      every permission-table lookup, so tool authority must be configured
      explicitly here -- see the module docstring.
    - A known preset seeds every tool name in that preset's set to
      ``frozenset({"admin"})``.
    - An unknown preset (not ``"none"`` and not a ``PERMISSION_PRESETS`` key)
      raises ``ValueError`` -- a silently-ignored typo'd preset name is
      exactly the class of bug this module exists to fix.
    - ``permissions`` (``tool_name -> [role, ...]``) is applied last and
      overrides any preset entry for the same tool name. An explicit entry
      with an empty role list produces ``frozenset()``, which denies
      *everyone* -- this is a deliberate hard deny, not a bug to "fix" into
      a no-op.
    """
    if preset not in VALID_PRESETS:
        valid = ", ".join(sorted(VALID_PRESETS))
        msg = f"Unknown permission preset '{preset}'. Valid values: {valid}."
        raise ValueError(msg)

    table: dict[str, frozenset[str]] = {}

    # "none" is simply absent from PERMISSION_PRESETS, so it seeds nothing.
    for name in PERMISSION_PRESETS.get(preset, frozenset()):
        table[name] = frozenset({"admin"})

    for tool_name, roles in permissions.items():
        table[tool_name] = frozenset(roles)

    return table


def describe_permission_table(table: PermissionTable) -> str:
    """Single log-safe line summarizing an armed (or empty) permission table."""
    names = ", ".join(sorted(table))
    return f"{len(table)} tool(s) restricted: [{names}]"
