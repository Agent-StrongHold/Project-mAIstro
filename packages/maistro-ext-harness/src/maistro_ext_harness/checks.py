"""Check records shared by the certification pipeline (M9-H3, #975).

A certification is a list of named checks with honest outcomes. The four
outcomes are exhaustive on purpose:

- ``passed`` — the check executed and held;
- ``failed`` — the check executed and did not hold (a decline reason);
- ``skipped`` — the check could not execute for an environment reason; a
  skipped *required* check fails certification under every profile that
  demands it, and is named in ``not_proven`` either way;
- ``not-applicable`` — the check does not apply to this artifact shape;
  recorded, never silent, and a strict profile declines on it.

There is no fifth outcome: a check that raises is contained by the
orchestrator and recorded as ``failed`` with the exception named, so a crash
can never look like a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["CheckRecord", "CheckStatus"]


class CheckStatus(StrEnum):
    """The honest outcomes. Absence is not an outcome."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not-applicable"


@dataclass(frozen=True)
class CheckRecord:
    """One named certification check and its outcome."""

    check_id: str
    description: str
    status: CheckStatus
    detail: str
    #: A required check's failure (or, under the profile's rules, its skip)
    #: declines certification. Everything in the certification pipeline is
    #: required; the flag exists so a future optional check cannot quietly
    #: soften the report's meaning.
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "description": self.description,
            "status": self.status.value,
            "detail": self.detail,
            "required": self.required,
        }
