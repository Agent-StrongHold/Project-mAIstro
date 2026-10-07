"""Validate parsed files against the front-matter schema.

`ValidationResult.warnings` is used for the rollout window: a missing
front-matter block produces a warning (not a hard error) until the
day-30 cutoff per `engine#ADR-031` §6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from maistro_registry.parser import parse_file
from maistro_registry.schema import FrontMatter, Status

#: Statuses whose document claims shipped, proven behavior. A `contracts:`
#: declaration without any cited test on top of one of these statuses is not
#: merely unfinished work — it is an implementation claim with no evidence
#: behind it (#812 AC-2), so it warns (and fails the strict gate) rather than
#: sitting in the debt bucket.
IMPLEMENTATION_CLAIM_STATUSES: frozenset[Status] = frozenset(
    {Status.IMPLEMENTED, Status.TESTS_PASSING}
)


@dataclass(frozen=True)
class ValidationResult:
    path: Path
    front_matter: FrontMatter | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Explicit, surfaced-but-non-failing states (#812 AC-2): a document may
    # declare contracts while citing no tests. That is debt — named, counted
    # in every lint summary, and distinct from a warning, which the strict
    # gate fails. Keeping debt out of `warnings` lets the corpus carry its
    # real backlog without turning every lint run red, while the
    # implementation-claiming statuses above escalate to warnings so an
    # implementation claim can never rest on an empty evidence field.
    debts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        """Human-readable rendering for CLI output."""
        lines = [str(self.path)]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        for d in self.debts:
            lines.append(f"  DEBT:  {d}")
        return "\n".join(lines)


def validate_file(path: Path | str) -> ValidationResult:
    p = Path(path)
    try:
        parsed = parse_file(p)
    except ValueError as exc:
        return ValidationResult(path=p, errors=[str(exc)])

    if parsed.front_matter is None:
        return ValidationResult(
            path=p,
            warnings=[
                "no front-matter block (per engine#ADR-031 §6, will be hard fail after day 30)"
            ],
        )

    try:
        fm = FrontMatter.model_validate(parsed.front_matter)
    except ValidationError as exc:
        msgs = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        return ValidationResult(path=p, errors=msgs)

    warnings, debts = _contract_evidence_state(fm)
    return ValidationResult(path=p, front_matter=fm, warnings=warnings, debts=debts)


def _contract_evidence_state(fm: FrontMatter) -> tuple[list[str], list[str]]:
    """Surface contracts declared without test citations, as (warnings, debts).

    Empty `warnings` when the document cites tests or declares no contracts —
    there is nothing to surface. Otherwise the state depends on what the
    document claims: a status inside IMPLEMENTATION_CLAIM_STATUSES warns
    (strict fails), every other status records an explicit debt.
    """
    if not fm.contracts or fm.tests:
        return [], []
    if fm.status in IMPLEMENTATION_CLAIM_STATUSES:
        return (
            [f"declares contracts but cites no tests while claiming status '{fm.status.value}'"],
            [],
        )
    return [], ["declares contracts but cites no tests (test-evidence debt)"]
