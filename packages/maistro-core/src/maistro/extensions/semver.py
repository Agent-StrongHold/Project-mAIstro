"""Strict semantic-version parsing and range matching for extension
dependency resolution (M9-C2, issue #956).

The extension contract (`docs/extensions/manifest-reference.md`) pins two
version surfaces:

* an extension's own version is strict ``MAJOR.MINOR.PATCH``;
* dependency and contract constraints are version *ranges* — comma-separated
  comparator clauses such as ``>=1.0.0,<2.0.0``.

This module is deliberately self-contained (stdlib only, like the rest of
``maistro.extensions``): dependency resolution must be reproducible from the
same inputs on every host, so it cannot lean on a resolver whose comparison
semantics drift with a third-party dependency bump. PEP 440 was rejected on
purpose — it coerces ``1.0.0`` to ``1.0``, gives pre-releases special
ordering, and accepts epoch/local forms none of which exist in the extension
contract. Here, everything outside ``X.Y.Z`` is a loud parse error, and the
only relation between versions is the numeric tuple order.

Ranges are pure data: :class:`VersionRange` is immutable, parsed once, and
asked ``satisfied_by(version)``. Parsing never inspects the clock, the
filesystem, or the network, so identical inputs always yield identical
resolution behavior — the property the lock state depends on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple

from maistro.extensions.types import ExtensionRegistryError

#: Strict ``MAJOR.MINOR.PATCH`` with semver.org's no-leading-zeros rule — the
#: only version form the contract allows. Strictness here is identity
#: hygiene: ``1.0.0`` and ``01.0.0`` must not be two spellings of one version.
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

#: Comparator operators, longest first so ``>=`` wins over ``>`` when a
#: clause is split into operator + bound.
_OPERATORS = (">=", "<=", "==", "!=", ">", "<")


class InvalidSemanticVersion(ExtensionRegistryError):
    """A version string is not strict ``MAJOR.MINOR.PATCH``."""


class InvalidVersionRange(ExtensionRegistryError):
    """A range string is not a comma-separated comparator list."""


class SemVer(NamedTuple):
    """One strict semantic version with tuple ordering.

    ``NamedTuple`` gives total ordering and hashability for free: ``1.2.3 <
    1.10.0`` holds because tuples compare numerically, which is exactly the
    ordering deterministic version selection needs. Every construction path
    goes through :meth:`parse`, so a ``SemVer`` in memory always came from a
    validated string (or was built field-wise by trusted code).
    """

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> SemVer:
        """Parse strict ``MAJOR.MINOR.PATCH``; anything else is an error."""
        match = _VERSION_RE.match(text.strip())
        if match is None:
            raise InvalidSemanticVersion(
                f"{text!r} is not a strict MAJOR.MINOR.PATCH version "
                "(the extension contract allows no pre-release, build metadata, "
                "'v' prefix, or partial forms)"
            )
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class VersionRange:
    """A parsed dependency range: every clause must hold (logical AND).

    ``clauses`` is the parsed form of the range text; the raw ``text`` is kept
    verbatim because diagnostics and lock entries quote the range exactly as
    it was declared — a paraphrased range in a conflict message would be one
    more thing for an operator to distrust.
    """

    text: str
    clauses: tuple[tuple[str, SemVer], ...]

    def satisfied_by(self, version: SemVer) -> bool:
        """True when ``version`` satisfies every clause."""
        return all(_CLAUSE_TESTS[operator](version, bound) for operator, bound in self.clauses)

    def violated_by_reason(self, version: SemVer) -> str | None:
        """The first clause ``version`` fails, quoted, or ``None``.

        Clause order follows the declared range, so the reason an operator
        sees is stable across runs — a deterministic first-failure, not a
        dict-order accident.
        """
        for operator, bound in self.clauses:
            if not _CLAUSE_TESTS[operator](version, bound):
                return f"fails '{operator}{bound}'"
        return None

    def __str__(self) -> str:
        return self.text


def _lt(version: SemVer, bound: SemVer) -> bool:
    return version < bound


def _le(version: SemVer, bound: SemVer) -> bool:
    return version <= bound


def _gt(version: SemVer, bound: SemVer) -> bool:
    return version > bound


def _ge(version: SemVer, bound: SemVer) -> bool:
    return version >= bound


def _eq(version: SemVer, bound: SemVer) -> bool:
    return version == bound


def _ne(version: SemVer, bound: SemVer) -> bool:
    return version != bound


_CLAUSE_TESTS = {
    "<": _lt,
    "<=": _le,
    ">": _gt,
    ">=": _ge,
    "==": _eq,
    "!=": _ne,
}


def _parse_clause(clause: str) -> tuple[str, SemVer]:
    """Split one comparator clause into (operator, bound)."""
    stripped = clause.strip()
    if stripped == "*":
        return (">=", SemVer(0, 0, 0))
    try:
        for operator in _OPERATORS:
            if stripped.startswith(operator):
                return (operator, SemVer.parse(stripped[len(operator) :]))
        # A bare version is an exact pin.
        return ("==", SemVer.parse(stripped))
    except InvalidSemanticVersion as exc:
        raise InvalidVersionRange(
            f"{clause.strip()!r} is not a valid comparator clause: {exc}"
        ) from exc


@lru_cache(maxsize=512)
def _parse_range_cached(text: str) -> VersionRange:
    if not text.strip():
        raise InvalidVersionRange("an empty string is not a version range; use '*' for any version")
    clauses = tuple(_parse_clause(clause) for clause in text.split(","))
    return VersionRange(text=text, clauses=clauses)


def parse_range(text: str) -> VersionRange:
    """Parse ``text`` as a comparator list; the result is immutable.

    ``*`` (any version) and empty-ish bounds parse to ``>=0.0.0``. Clauses are
    AND-ed together, matching the documented contract form ``>=1.0.0,<2.0.0``.
    The parse is cached because resolution re-checks the same declared range
    against many candidates; the cache is safe because ranges are immutable
    and parsing is pure.
    """
    return _parse_range_cached(text)
