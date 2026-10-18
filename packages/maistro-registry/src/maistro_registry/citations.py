"""Governing citations must resolve to active authority (#374).

`linker.check_links` asks whether a cited document *exists*. That is a weaker
question than the one that matters, and the gap is populated: an Accepted spec
may name a Deprecated ADR as its substrate, or a Proposed one, and nothing
notices. The citation reads as authority to anyone following it, and the
authority is not there.

## Which citations govern

Not all of them, and treating them alike would be its own error — most of a
document's relationships are navigational.

- **Governing**: `substrate` and `implements`. "This rests on that decision" and
  "this implements that decision" are both normative claims about live
  authority.
- **Historical by construction**: `supersedes`. Naming what you replaced is a
  statement about the past, and requiring its target to be active would make
  every supersession self-contradictory.
- **Navigational**: `related`, `blocks`, `blocked_by`. These order work and
  point at neighbours; none of them claims authority.

## Which sources are held to it

A document that has not shipped cannot govern anything, so it is not held to
this rule: a `Proposed` ADR may rest on another `Proposed` ADR while both are
being worked out. The rule binds documents in an **active** state — the ones a
reader would take as describing what the system does now.

That asymmetry is the whole point of the check. `Proposed` decisions silently
governing shipped behaviour is the specific failure #374 names, and it is
invisible precisely because the citation looks identical either way.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from maistro_registry.schema import FrontMatter, Status

#: Relationship fields that assert live authority.
GOVERNING_FIELDS: tuple[str, ...] = ("substrate", "implements")

#: Statuses in which a document describes what the system does now, and so may
#: not rest on authority that is not itself live.
ACTIVE_SOURCE_STATUSES: frozenset[Status] = frozenset(
    {
        Status.ACCEPTED,
        Status.FULLY_SPECCED,
        Status.AC_DEFINED,
        Status.IN_PROGRESS,
        Status.TESTS_PASSING,
        Status.IMPLEMENTED,
    }
)

#: Statuses in which a document may be cited as governing authority.
ACTIVE_AUTHORITY_STATUSES: frozenset[Status] = frozenset({Status.ACCEPTED, Status.IMPLEMENTED})


@dataclass(frozen=True)
class CitationProblem:
    """One governing citation that does not resolve to active authority."""

    source: str
    field_name: str
    target: str
    reason: str

    def render(self) -> str:
        return f"{self.source}.{self.field_name} -> {self.target}: {self.reason}"


def _index(front_matters: list[FrontMatter]) -> dict[str, FrontMatter]:
    return {f"{fm.repo.value}#{fm.id}": fm for fm in front_matters}


def _walk_replacement(
    current: FrontMatter,
    path: tuple[str, ...],
    index: dict[str, FrontMatter],
    cache: dict[str, tuple[dict[str, FrontMatter], tuple[str, ...]]],
) -> tuple[dict[str, FrontMatter], tuple[str, ...]]:
    """Collect active endpoints and broken links from one supersession branch."""
    key = f"{current.repo.value}#{current.id}"
    result: tuple[dict[str, FrontMatter], tuple[str, ...]]
    if key in path:
        return {}, (f"supersession chain cycles at {key}",)
    if key in cache:
        return cache[key]

    if current.status in ACTIVE_AUTHORITY_STATUSES:
        result = ({key: current}, ())
        cache[key] = result
        return result
    if current.status is not Status.SUPERSEDED:
        result = ({}, (f"chain ends at {key}, which is {current.status.value}",))
        cache[key] = result
        return result

    successors = list(dict.fromkeys(current.superseded_by))
    if not successors:
        result = ({}, (f"{key} is Superseded but names no replacement",))
        cache[key] = result
        return result

    authorities: dict[str, FrontMatter] = {}
    problems: list[str] = []
    next_path = (*path, key)
    for successor in successors:
        replacement = index.get(successor)
        if replacement is None:
            problems.append(f"{key} names replacement {successor} which does not exist")
            continue
        branch_authorities, branch_problems = _walk_replacement(
            replacement, next_path, index, cache
        )
        authorities.update(branch_authorities)
        problems.extend(branch_problems)

    result = (authorities, tuple(dict.fromkeys(problems)))
    cache[key] = result
    return result


def _replacement_chain(
    start: FrontMatter, index: dict[str, FrontMatter]
) -> tuple[FrontMatter | None, str | None]:
    """Resolve every supersession branch to its active authority.

    A supersession can have more than one successor, and each successor can in
    turn branch again. Walking only the first active successor would hide a
    contradictory authority on another branch (or hide a cycle behind it), so
    this is a graph walk rather than a single-chain lookup. Converging branches
    are deduplicated by document identity; two distinct active endpoints remain
    contradictory even when their statuses match.
    """
    # Cache completed subgraphs so a shared successor is traversed once. The
    # path tuple is still checked before the cache: a back-edge is a cycle only
    # when it returns to the current recursion path.
    cache: dict[str, tuple[dict[str, FrontMatter], tuple[str, ...]]] = {}
    key = f"{start.repo.value}#{start.id}"
    authorities, problems = _walk_replacement(start, (), index, cache)
    if len(authorities) > 1:
        replacements = sorted(authorities)
        return None, f"{key} names more than one active replacement: {replacements}"
    if problems:
        return None, "; ".join(problems)
    if authorities:
        return next(iter(authorities.values())), None
    # The walk can only reach this state if the status vocabulary changes
    # without adding a terminal outcome; keep the checker fail-closed.
    return None, f"{key} has no active replacement"


def check_citations(front_matters: list[FrontMatter]) -> list[CitationProblem]:
    """Every governing citation from an active document, checked for authority."""
    index = _index(front_matters)
    references = (
        (f"{fm.repo.value}#{fm.id}", field_name, ref)
        for fm in front_matters
        if fm.status in ACTIVE_SOURCE_STATUSES
        for field_name in GOVERNING_FIELDS
        for ref in list(getattr(fm, field_name))
    )
    return _check_references(references, index)


def check_governing_references(
    references: Iterable[tuple[str, str, str]], front_matters: list[FrontMatter]
) -> list[CitationProblem]:
    """Check governing references from non-front-matter governance surfaces.

    The convergence matrix is an active planning surface rather than an ADR or
    spec, so it cannot be represented by ``FrontMatter``. It still needs the
    same target-status and supersession rules; callers provide its source and
    relationship labels explicitly and this function shares the exact checker.
    """
    return _check_references(references, _index(front_matters))


def _check_references(
    references: Iterable[tuple[str, str, str]], index: dict[str, FrontMatter]
) -> list[CitationProblem]:
    problems: list[CitationProblem] = []
    for source, field_name, ref in references:
        problem = _check_one(source, field_name, ref, index)
        if problem is not None:
            problems.append(problem)
    return problems


def _check_one(
    source: str, field_name: str, ref: str, index: dict[str, FrontMatter]
) -> CitationProblem | None:
    target = index.get(ref)
    if target is None:
        # Existence is `linker.check_links`'s job, and reporting it here too
        # would give one defect two voices in one run.
        return None

    if target.status in ACTIVE_AUTHORITY_STATUSES:
        return None

    if target.status is Status.SUPERSEDED:
        replacement, problem = _replacement_chain(target, index)
        if replacement is not None:
            return CitationProblem(
                source=source,
                field_name=field_name,
                target=ref,
                reason=(
                    f"is Superseded by {replacement.repo.value}#{replacement.id}; cite the "
                    "active replacement, or move this to `related` if the reference is historical"
                ),
            )
        return CitationProblem(
            source=source, field_name=field_name, target=ref, reason=str(problem)
        )

    return CitationProblem(
        source=source,
        field_name=field_name,
        target=ref,
        reason=(
            f"is {target.status.value} and cannot govern an active document; "
            "a decision that has not been accepted cannot be authority for shipped behaviour"
        ),
    )


# --- the ratchet -------------------------------------------------------------
#
# The baseline is intentionally identity-based even when empty: it keeps the
# CI gate useful while a governance cleanup is in flight, and ensures future
# exceptions cannot be hidden by changing the wording of a diagnostic. A fixed
# citation must remove its ledger entry in the same change.


@dataclass(frozen=True)
class CitationBaseline:
    """Reviewed set of known-bad citations, keyed by identity not by count."""

    entries: frozenset[str]

    @classmethod
    def of(cls, problems: list[CitationProblem]) -> CitationBaseline:
        return cls(entries=frozenset(_identity(p) for p in problems))

    def partition(self, problems: list[CitationProblem]) -> tuple[list[CitationProblem], list[str]]:
        """Split into (unbaselined problems, stale baseline entries).

        Stale entries are returned so a fixed citation must shrink the ledger in
        the same change: a baseline that keeps an entry after the defect is gone
        silently absorbs the next regression at that identity.
        """
        seen = {_identity(p) for p in problems}
        new = [p for p in problems if _identity(p) not in self.entries]
        stale = sorted(self.entries - seen)
        return new, stale


def _identity(problem: CitationProblem) -> str:
    """Source, field and target — not the reason.

    The reason is prose and will be reworded; the citation it describes is the
    thing being tracked. Keying on the message would turn every improvement to
    an error string into a wave of phantom new findings.
    """
    return f"{problem.source}.{problem.field_name} -> {problem.target}"


__all__ = [
    "ACTIVE_AUTHORITY_STATUSES",
    "ACTIVE_SOURCE_STATUSES",
    "GOVERNING_FIELDS",
    "CitationBaseline",
    "CitationProblem",
    "check_citations",
    "check_governing_references",
]
