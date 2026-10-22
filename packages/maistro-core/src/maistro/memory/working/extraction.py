"""Entity extraction for the working graph (ADR-082226-5104 §5, issue #301).

Two implementations, one protocol:

* :class:`LexicalEntityExtractor` — the no-LLM path every ordinary operation
  uses. Deterministic, dependency-free, and cheap enough to run at hydrate
  time on every record.
* :class:`GovernedEntityExtractor` — the optional complex-extraction path.
  The model call itself is *not made here*: the caller injects an async
  callable that already runs through MAIstro's governed model/effect path.
  The adapter never imports LiteLLM or any provider client, so a memory
  module cannot grow a second, ungoverned route to a model.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

#: Multi-word proper-noun sequences ("Zanzibar City") and single tokens
#: ("PostgreSQL"). The match is deliberately conservative about what counts
#: as a word: letters, digits and internal apostrophes/underscores.
_PROPER_NOUN = re.compile(
    r"\b(?:[A-Z][a-z0-9_']*(?:\s+[A-Z][a-z0-9_']*)+)\b|\b[A-Z][A-Za-z0-9_']+\b"
)

#: Tokens that are capitalized mid-sentence far more often as ordinary words
#: than as names. A stoplist, not an ontology: the extractor errs toward
#: missing an entity over inventing one, because a wrong entity pollutes
#: traversal, while a missing one only narrows it.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "i",
        "my",
        "we",
        "this",
        "that",
        "these",
        "those",
        "there",
        "then",
        "when",
        "what",
        "who",
        "how",
        "why",
        "not",
        "no",
        "yes",
        "do",
        "does",
        "did",
        "done",
    }
)


def _normalized(name: str) -> str:
    return name.strip().lower()


class LexicalEntityExtractor:
    """No-LLM entity extraction: capitalized sequences plus declared entities.

    A sequence of capitalized words is a candidate name ("New York", "Ada
    Lovelace"); a lone capitalized token qualifies too. The stoplist keeps
    ordinary capitalized sentence words ("The", "But") out; the extractor
    errs toward missing an entity over inventing one, because a wrong entity
    pollutes traversal while a missing one only narrows it.
    ``EpisodicMemory.context["entities"]`` always wins — a producer that
    names its entities explicitly is not second-guessed.
    """

    def __init__(self, *, min_length: int = 3, max_per_record: int = 16) -> None:
        self._min_length = min_length
        self._max_per_record = max_per_record

    async def extract(self, text: str, *, declared: Iterable[str] = ()) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()

        def add(candidate: str) -> None:
            name = _normalized(candidate)
            if len(name) < self._min_length or name in _STOPWORDS or name in seen:
                return
            if not any(ch.isalpha() for ch in name):
                return
            seen.add(name)
            found.append(candidate.strip())

        for name in declared:
            add(name)

        for match in _PROPER_NOUN.finditer(text):
            add(match.group(0))
            if len(found) >= self._max_per_record:
                break
        return found


@runtime_checkable
class EntityExtractor(Protocol):
    """Extracts entity names for one record's text."""

    async def extract(self, text: str, *, declared: Iterable[str] = ()) -> list[str]: ...


class GovernedEntityExtractor:
    """Optional extraction backed by a caller-supplied governed model call.

    ``extract_fn`` receives the record text and returns entity names. It is
    whatever the caller wires through MAIstro's governed model/effect path
    (a capability-scoped tool effect, typically). Any failure of that path is
    an ``Exception`` like any other: the caller sees it, or the manager
    records the degradation — it is never swallowed into "no entities".
    """

    def __init__(self, extract_fn: Callable[[str], Awaitable[list[str]]]) -> None:
        self._extract_fn = extract_fn

    async def extract(self, text: str, *, declared: Iterable[str] = ()) -> list[str]:
        extracted = await self._extract_fn(text)
        names = list(dict.fromkeys([*declared, *extracted]))
        return [name for name in names if name.strip()]
