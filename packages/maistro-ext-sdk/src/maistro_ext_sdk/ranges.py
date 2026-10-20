"""Version and version-range parsing for the extension contract.

Deliberately tiny and dependency-free. The ranges the manifest contract
expresses are the capping convention this monorepo already uses everywhere
(``>=X,<X+1`` per ADR-073126-c4e1), so the parser accepts exactly the
specifier set that convention needs — ``>=``, ``>``, ``==``, ``<``, ``<=``
over ``MAJOR.MINOR.PATCH`` versions, comma-joined — and rejects everything
else *explicitly*. A silent permissive parser would let a manifest that
means "contract 2 only" validate against a v1 SDK, which is precisely the
authority-creep the manifest exists to prevent.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable

from maistro_ext_sdk.contract import ContractVersion, parse_contract_version

__all__ = ["VersionRange", "parse_version_range"]
_OP_RE = re.compile(r"^(>=|<=|==|>|<)\s*(\d+\.\d+\.\d+)$")

#: The comparison each specifier operator asks of its bound. Keyed by the
#: exact tokens ``_OP_RE`` accepts, so the parser and this table must agree:
#: an operator reachable here but not in the regex — or the other way —
#: would mean a range text whose meaning nobody defined.
_OPS: dict[str, Callable[[ContractVersion, ContractVersion], bool]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "==": operator.eq,
    "<": operator.lt,
    "<=": operator.le,
}


class VersionRange:
    """A comma-separated set of version specifiers over contract versions.

    ``VersionRange(">=1.0.0,<2.0.0").satisfied_by(ContractVersion(1, 4, 2))`` is
    the compatibility question every host asks of every manifest.
    """

    __slots__ = ("_specs", "_text")

    def __init__(self, text: str) -> None:
        self._text = text
        specs: list[tuple[str, ContractVersion]] = []
        for raw in text.split(","):
            token = raw.strip()
            if not token:
                raise ValueError(f"empty specifier in version range {text!r}")
            m = _OP_RE.match(token)
            if m is None:
                raise ValueError(
                    f"unsupported version specifier {token!r} in range {text!r}: expected "
                    f">=, >, ==, <, or <= over MAJOR.MINOR.PATCH"
                )
            specs.append((m.group(1), parse_contract_version(m.group(2))))
        self._specs = tuple(specs)

    @classmethod
    def parse(cls, text: str) -> VersionRange:
        """Named constructor so callers read as intent, not as construction."""
        return cls(text)

    def satisfied_by(self, version: ContractVersion) -> bool:
        """Whether ``version`` satisfies every specifier in the range."""
        return all(_OPS[op](version, bound) for op, bound in self._specs)

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:  # pragma: no cover - debug surface
        return f"VersionRange({self._text!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VersionRange):
            return NotImplemented
        return self._specs == other._specs

    def __hash__(self) -> int:
        return hash(self._specs)


def parse_version_range(text: str) -> VersionRange:
    """Parse a ``">=1.0.0,<2.0.0"``-style range; explicit error otherwise."""
    return VersionRange(text)
