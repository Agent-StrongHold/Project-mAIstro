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

from dataclasses import dataclass

from maistro_registry.schema import FrontMatter, Status

#: Relationship fields that assert live authority.
GOVERNING_FIELDS: tuple[str, ...] = ("substrate", "implements")

#: Statuses in which a document describes what the system does now, and so may
#: not rest on authority that is not itself live.
ACTIVE_SOURCE_STATUSES: frozenset[Status] = frozenset(
    {
        Status.ACCEPTED,
        Status.IMPLEMENTED,
        Status.FULLY_SPECCED,
        Status.TESTS_PASSING,
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


def _next_in_chain(
    current: FrontMatter, key: str, index: dict[str, FrontMatter]
) -> tuple[FrontMatter | None, str | None]:
    """The single successor of a Superseded document, or why there isn't one."""
    successors = list(current.superseded_by)
    if not successors:
        return None, f"{key} is Superseded but names no replacement"
    if len(successors) > 1:
        resolved = [ref for ref in successors if ref in index]
        live = {index[ref].status for ref in resolved} & ACTIVE_AUTHORITY_STATUSES
        if len(live) > 1:
            return None, f"{key} names more than one active replacement: {successors}"
    nxt = index.get(successors[0])
    if nxt is None:
        return None, f"{key} names replacement {successors[0]} which does not exist"
    return nxt, None


def _replacement_chain(
    start: FrontMatter, index: dict[str, FrontMatter]
) -> tuple[FrontMatter | None, str | None]:
    """Walk `superseded-by` to the document that now holds the authority.

    Returns `(active_replacement, problem)`; exactly one is not `None`.

    The walk is bounded by a seen-set rather than a depth limit because the
    failure it guards against is a cycle — A superseded by B superseded by A —
    and a cycle has no depth at which it becomes legitimate. A chain that ends
    somewhere inactive is reported at its end, not at its start, so the reader
    is told which link actually broke.
    """
    seen: set[str] = set()
    current = start
    while True:
        key = f"{current.repo.value}#{current.id}"
        if key in seen:
            return None, f"supersession chain cycles at {key}"
        seen.add(key)

        if current.status in ACTIVE_AUTHORITY_STATUSES:
            return current, None
        if current.status is not Status.SUPERSEDED:
            return None, f"chain ends at {key}, which is {current.status.value}"

        nxt, problem = _next_in_chain(current, key, index)
        if nxt is None:
            return None, problem
        current = nxt


def check_citations(front_matters: list[FrontMatter]) -> list[CitationProblem]:
    """Every governing citation from an active document, checked for authority."""
    index = _index(front_matters)
    problems: list[CitationProblem] = []

    for fm in front_matters:
        if fm.status not in ACTIVE_SOURCE_STATUSES:
            continue
        source = f"{fm.repo.value}#{fm.id}"
        for field_name in GOVERNING_FIELDS:
            for ref in list(getattr(fm, field_name)):
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
# Turning this on found 47 governing citations already in the corpus, in exactly
# the classes #374 names: Superseded ADRs cited as substrate, Deprecated ones
# named by `implements`, and Proposed decisions governing shipped specs.
#
# They are baselined rather than fixed here, for the reason this repository
# baselines everywhere else: the fix for each is a governance judgement, not a
# mechanical edit. "SPEC-182 implements ADR-058, which is Proposed" is answered
# either by accepting ADR-058 or by demoting the claim, and those say different
# things about what shipped. A blanket rewrite would launder 47 such judgements
# into one diff nobody could review.
#
# What the baseline does buy immediately is that no *new* one can land.


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
]
