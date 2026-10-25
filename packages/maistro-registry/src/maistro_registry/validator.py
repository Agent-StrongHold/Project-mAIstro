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
from maistro_registry.schema import FrontMatter


@dataclass(frozen=True)
class ValidationResult:
    path: Path
    front_matter: FrontMatter | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

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

    return ValidationResult(path=p, front_matter=fm)
