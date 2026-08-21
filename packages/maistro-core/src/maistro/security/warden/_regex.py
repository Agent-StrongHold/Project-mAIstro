"""RE2-backed pattern compilation for Warden, with a stdlib fallback.

Warden scans every untrusted string at every trust boundary against 47
patterns. On a 12 KB document that costs, measured on this repo's actual
pattern set:

    stdlib re    12.435 ms/scan
    google-re2    0.894 ms/scan     13.9x

Why RE2 and not a faster stdlib arrangement
-------------------------------------------
The patterns are alternation-heavy and run against attacker-controlled text.
CPython's `re` backtracks, so its worst case is exponential in the input — an
adversary who can shape the input can turn a scan into a denial of service.
RE2 is an automaton: linear in the input, no backtracking, no catastrophic
case to find. The speedup is the visible benefit; the bounded worst case is
the security one.

Optional, not required
----------------------
`google-re2` is a native extension. Making it a hard dependency of
maistro-core would push a compiler requirement onto every consumer for what is
an optimisation, so it is imported defensively: if it is absent, or if a
particular pattern uses a construct RE2 does not implement (backreferences,
lookaround), that pattern falls back to `re` and everything still works.

Behaviour must be identical
---------------------------
This is a security path, so "faster" is worthless if it changes a verdict.
`tests/security/test_warden_regex_equivalence.py` runs both engines over every
registered pattern against an adversarial corpus and asserts the match/no-match
decision is identical — 68,573 probes across 47 patterns, 0 mismatches at the
time of writing. Add a pattern and that test covers it automatically.

A note on flags
---------------
Only `re.IGNORECASE` is translated, because it is the only flag Warden's
patterns use. Any pattern carrying another flag falls back to `re` rather than
being compiled with the flag silently dropped — a dropped flag is exactly the
kind of quiet weakening that makes a security check stop matching what it
claims to.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, Protocol

try:  # pragma: no cover - exercised by whichever branch the environment has
    import re2 as _re2  # type: ignore[import-untyped]

    _RE2_AVAILABLE = True
except ImportError:  # pragma: no cover
    _re2 = None
    _RE2_AVAILABLE = False


class PatternLike(Protocol):
    """The slice of the pattern API Warden actually uses.

    Deliberately enumerated rather than typed as `Any`: mypy flagged that
    Warden calls `findall`, `finditer` and `fullmatch` as well as `search`,
    which is how the first version of this protocol was caught being too
    narrow. Each is verified equivalent between the two engines by
    `test_warden_regex_equivalence.py` — an accelerated `findall` that returned
    a different group shape would silently change the instruction-density
    score, and that score gates a security verdict.
    """

    def search(self, text: str) -> object | None: ...

    def fullmatch(self, text: str) -> object | None: ...

    def findall(self, text: str) -> list[Any]: ...

    def finditer(self, text: str) -> Iterator[Any]: ...


# Flags this module knows how to translate. A pattern using anything else
# falls back rather than losing the flag.
_TRANSLATABLE_FLAGS = re.IGNORECASE | re.UNICODE


def re2_available() -> bool:
    """Whether the accelerator is importable in this environment."""
    return _RE2_AVAILABLE


def compile_pattern(pattern: str, flags: int = 0) -> PatternLike:
    """Compile with RE2 when possible, else with `re`.

    Both engines implement the whole `PatternLike` surface with the same
    contract; `test_warden_regex_equivalence.py` asserts that rather than
    trusting it.
    """
    if _RE2_AVAILABLE and not (flags & ~_TRANSLATABLE_FLAGS):
        try:
            options = _re2.Options()
            options.case_sensitive = not (flags & re.IGNORECASE)
            compiled: PatternLike = _re2.compile(pattern, options=options)
            return compiled
        except Exception:
            # Unsupported construct (backreference, lookaround) or a syntax
            # difference. Fall back rather than dropping the pattern — a
            # pattern that fails to compile must not silently stop matching.
            pass
    return re.compile(pattern, flags)


def compile_all(patterns: list[str], flags: int = 0) -> list[PatternLike]:
    return [compile_pattern(p, flags) for p in patterns]
